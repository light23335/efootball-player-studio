"""Pure, reproducible CPU fixture score simulation from actual squad ratings.

Only the five numeric squad dimensions enter the score model. Team names,
identities, fame, tournament rewards, and difficulty do not enter it. All
constants below are explicit game-design calibration, not fitted statistics.

The joint score law is Dixon & Coles (1997), p. 270, equation (4.2):
    P(x,y) = tau(x,y) Poisson(x; lambda) Poisson(y; mu).
Primary paper: https://doi.org/10.1111/1467-9876.00065
Open copy of the original authors' paper used to verify the four tau branches:
https://ajbuckeconbikesail.net/wkpapers/Airports/MVPoisson/soccer_betting.pdf
The rating-to-xG link, form rule, home effect, and penalty probabilities are
our bounded design choices; they are not claimed to come from that paper.
"""

import hashlib
import json
import math
import random
from collections.abc import Mapping


MODEL_VERSION = "poisson-dixon-coles-v1"
RATING_KEYS = ("attack", "creation", "defence", "goalkeeping", "depth")
BASE_XG = 1.3
STRENGTH_LOG_LIMIT = 1.15
STRENGTH_SCALE = 35.0
HOME_LOG_EFFECT = 0.06
FORM_LOG_EFFECT = 0.035
DEFAULT_RHO = -0.08
PENALTY_BASE = 0.75
PENALTY_EFFECT_LIMIT = 0.09
PENALTY_TAKER_FIELDS = {20: .50, 27: .30, 28: .10, 37: .10}
PENALTY_KEEPER_FIELDS = {16: .25, 29: .15, 30: .15, 31: .30, 32: .15}
PAPER = "https://doi.org/10.1111/1467-9876.00065"
PENALTY_RULES = "https://theifab.com/laws/latest/determining-the-outcome-of-a-match/"


def derive_seed(root_seed, *labels):
    """Derive a named random stream without consuming any other stream.

    JSON encodes type and label boundaries (1 and '1' remain distinct).
    No process-randomized hash(), clock, global random state or file I/O.
    """
    if isinstance(root_seed, bool) or not isinstance(root_seed, (int, str)):
        raise ValueError("root_seed must be an integer or string")
    if not all(isinstance(label, (str, int)) and not isinstance(label, bool)
               for label in labels):
        raise ValueError("seed labels must be integers or strings")
    payload = json.dumps([MODEL_VERSION, root_seed, *labels],
                         ensure_ascii=False, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:16], "big")


def seed_streams(root_seed, fixture_id):
    """Independent roster / regulation / extra-time / penalty streams."""
    return {name: derive_seed(root_seed, fixture_id, name)
            for name in ("roster", "regulation", "extra_time", "penalties")}


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(label + " must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(label + " must be a finite number")
    return value


def _ratings(value):
    if not isinstance(value, Mapping):
        raise ValueError("ratings must contain all five numeric dimensions")
    return {key: _finite_number(value.get(key), key) for key in RATING_KEYS}


def _seed(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("seed must be an integer")
    return value


def _model_version(version):
    # Archived editions must fail explicitly if their implementation is not
    # available; upgrading a competition must never silently reroll its model.
    if version != MODEL_VERSION:
        raise ValueError("unsupported simulation model version: " + str(version))
    return version


def _count(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(label + " must be a nonnegative integer")
    return value


def form_state(history=None):
    """Normalize previous results, oldest first, or an explicit streak state.

    A draw is a non-win and breaks a win streak. A win clears non-wins.
    Streak length never multiplies the one active form adjustment.
    """
    if history is None:
        return {"win_streak": 0, "nonwin_streak": 0}
    if isinstance(history, Mapping):
        wins = _count(history.get("win_streak", 0), "win_streak")
        nonwins = _count(history.get("nonwin_streak", 0), "nonwin_streak")
        if wins and nonwins:
            raise ValueError("win_streak and nonwin_streak cannot both be active")
        return {"win_streak": wins, "nonwin_streak": nonwins}
    if isinstance(history, (str, bytes)):
        raise ValueError("history must be a W/D/L sequence, not a string")
    try:
        outcomes = iter(history)
    except TypeError as exc:
        raise ValueError("form must be a streak state or W/D/L sequence") from exc
    result = form_state()
    for outcome in outcomes:
        result = advance_form(result, outcome)
    return result


def advance_form(state, outcome):
    """Return new streak counters; do not alter the caller's saved state."""
    state = form_state(state)
    if outcome not in ("W", "D", "L"):
        raise ValueError("outcome must be W, D or L")
    if outcome == "W":
        return {"win_streak": state["win_streak"] + 1, "nonwin_streak": 0}
    return {"win_streak": 0, "nonwin_streak": state["nonwin_streak"] + 1}


def form_modifier(state=None):
    """One small log-xG adjustment after three wins or three non-wins."""
    state = form_state(state)
    if state["win_streak"] >= 3:
        return FORM_LOG_EFFECT
    if state["nonwin_streak"] >= 3:
        return -FORM_LOG_EFFECT
    return 0.0


def _strength(own, opponent):
    # All five dimensions participate. Each comparison has a football role;
    # no overall/name coefficient is added on top of squad strength.
    terms = {
        "attack_vs_defence": 0.42 * (own["attack"] - opponent["defence"]),
        "creation_vs_defence": 0.23 * (own["creation"] - opponent["defence"]),
        "attack_vs_goalkeeping": 0.25 * (own["attack"] - opponent["goalkeeping"]),
        "depth_difference": 0.10 * (own["depth"] - opponent["depth"]),
    }
    difference = sum(terms.values())
    effect = STRENGTH_LOG_LIMIT * math.tanh(difference / STRENGTH_SCALE)
    return effect, {"weighted_terms": terms, "difference": difference,
                    "strength_log": effect, "strength_multiplier": math.exp(effect)}


def expected_goals(home_ratings, away_ratings, *, minutes=90, neutral=False,
                   form_home=None, form_away=None, model_version=MODEL_VERSION):
    """Return xG and transparent bounded modifiers, without drawing a score.

    Equal five-dimension ratings on neutral ground with no active form give
    1.3 xG per side per 90 minutes. Higher finishing/creation raises a side's
    xG; better opposing defence/keeping lowers it. tanh smoothly limits the
    log-strength effect even for out-of-range input; input is not hard-clipped.
    Extra time is an independent period with xG scaled by 30/90, when asked
    for by competition rules. This function never decides to play extra time.
    """
    _model_version(model_version)
    home, away = _ratings(home_ratings), _ratings(away_ratings)
    minutes = _finite_number(minutes, "minutes")
    if not 0 <= minutes <= 120:
        raise ValueError("a simulated period must last 0 to 120 minutes")
    if not isinstance(neutral, bool):
        raise ValueError("neutral must be a boolean")
    forms = [form_state(form_home), form_state(form_away)]
    modifiers, xg_90 = {}, []
    for index, (side, own, opponent) in enumerate(
            (("home", home, away), ("away", away, home))):
        strength, audit = _strength(own, opponent)
        home_effect = 0.0 if neutral else (HOME_LOG_EFFECT if index == 0 else -HOME_LOG_EFFECT)
        form_effect = form_modifier(forms[index])
        total = strength + home_effect + form_effect
        value = BASE_XG * math.exp(total)
        audit.update(form_state=forms[index], form_log=form_effect,
                     form_multiplier=math.exp(form_effect), home_log=home_effect,
                     home_multiplier=math.exp(home_effect), total_log=total,
                     total_multiplier=math.exp(total))
        modifiers[side] = audit
        xg_90.append(value)
    return {"xg": [value * minutes / 90.0 for value in xg_90],
            "xg_90": xg_90, "minutes": minutes, "neutral": neutral,
            "modifiers": modifiers, "model_version": MODEL_VERSION,
            "audit": {"ratings": {"home": home, "away": away},
                      "base_xg_90": BASE_XG, "strength_log_limit": STRENGTH_LOG_LIMIT,
                      "strength_scale": STRENGTH_SCALE, "form_log_limit": FORM_LOG_EFFECT,
                      "home_log_effect": HOME_LOG_EFFECT,
                      "calibration": "explicit design constants; not historical fitted parameters",
                      "source": PAPER, "score_support": "nonnegative integers, no goal cap"}}


def dixon_coles_tau(home_goals, away_goals, home_xg, away_xg, rho=DEFAULT_RHO):
    """Original paper eq. (4.2), not an arbitrary draw/score replacement."""
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_xg * away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def _poisson(rate, rng):
    # Exact product sampler for our bounded (<6.1 xG/period) means. The loop
    # has no goal-count cut-off: seven, eight, etc. remain possible.
    if rate == 0:
        return 0
    threshold = math.exp(-rate)
    product, count = 1.0, 0
    while product > threshold:
        product *= rng.random()
        count += 1
    return count - 1


def sample_period(home_ratings, away_ratings, *, seed, minutes=90, neutral=False,
                  form_home=None, form_away=None, model_version=MODEL_VERSION):
    """Draw an exact DC joint score by rejection from unbounded Poisson.

    Total probability is already one and the Poisson marginals are preserved.
    No truncated grid, renormalized 0..6 table, or forced winner is used.
    """
    seed = _seed(seed)
    result = expected_goals(home_ratings, away_ratings, minutes=minutes,
                            neutral=neutral, form_home=form_home, form_away=form_away,
                            model_version=model_version)
    home_xg, away_xg = result["xg"]
    # For general future period calibrations keep rho strictly inside the
    # paper's admissible range, so all four tau factors remain nonnegative.
    max_rate = max(home_xg, away_xg)
    rho = max(DEFAULT_RHO, -0.95 / max_rate) if max_rate else DEFAULT_RHO
    envelope = max(1.0, *(dixon_coles_tau(x, y, home_xg, away_xg, rho)
                          for x, y in ((0, 0), (0, 1), (1, 0), (1, 1))))
    rng, attempts = random.Random(seed), 0
    while True:
        attempts += 1
        score = [_poisson(home_xg, rng), _poisson(away_xg, rng)]
        tau = dixon_coles_tau(*score, home_xg, away_xg, rho)
        if rng.random() * envelope < tau:
            break
    result.update(score=score, seed=seed)
    result["modifiers"]["rho"] = rho
    result["audit"].update(sampler="unbounded Poisson rejection with exact DC tau",
                            rejection_attempts=attempts, tau=tau,
                            tau_envelope=envelope, rho=rho)
    return result


def simulate_match(home_ratings, away_ratings, *, root_seed, match_id,
                   neutral=False, home_form=None, away_form=None,
                   duration_minutes=90, stage="regulation", model_version=MODEL_VERSION):
    """Convenient named-stream wrapper; rules still decide whether ET/PK play."""
    if stage not in ("regulation", "extra_time"):
        raise ValueError("stage must be regulation or extra_time")
    return sample_period(home_ratings, away_ratings,
                         seed=derive_seed(root_seed, match_id, stage),
                         minutes=duration_minutes, neutral=neutral,
                         form_home=home_form, form_away=away_form,
                         model_version=model_version)


def _penalty_probability(taker_ability, keeper_ability):
    effect = PENALTY_EFFECT_LIMIT * math.tanh((taker_ability - keeper_ability) / 35.0)
    return PENALTY_BASE + effect, effect


def _effective_fields(player, weights):
    effective = player.get("effective")
    if not isinstance(effective, Mapping):
        raise ValueError("actual penalty player is missing effective abilities")
    # Persisted JSON converts integer parameter keys to strings. Both encode
    # the same already-applied, actual entry ability; never boost it again.
    return {field: _finite_number(effective.get(field, effective.get(str(field))),
                                  "effective ability " + str(field))
            for field in weights}


def _penalty_player(player, weights):
    ident = player.get("gameplayer_id")
    if (not isinstance(ident, Mapping)
            or any(type(ident.get(key)) is not int or ident[key] < 0 for key in ("id", "serial"))):
        raise ValueError("actual penalty player is missing native identity")
    effective = _effective_fields(player, weights)
    return {"gameplayer_id": {key: ident[key] for key in ("id", "serial")},
            "order": player["order"], "roster_index": player["roster_index"],
            "effective": effective,
            "ability": sum(effective[field] * weight for field, weight in weights.items())}


def _penalty_squad(source, numbers):
    """Resolve only the actual XI and actual goalkeeper from a ratings audit.

    A numeric-only mathematical test can use an explicitly labelled proxy.
    If real player audit data are present, incomplete/invalid data must fail;
    silently downgrading a real fixture to the proxy is forbidden.
    """
    audit = source.get("audit")
    if (isinstance(audit, Mapping) and "players" not in audit
            and ("revision" in audit or "snapshot_sha256" in audit)):
        raise ValueError("actual penalty ratings audit is missing the starting players")
    if not isinstance(audit, Mapping) or "players" not in audit:
        return {"source": "numeric_only_proxy", "order_policy": "single mathematical proxy, not a real player",
                "takers": [{"gameplayer_id": None, "effective": None,
                            "ability": .75 * numbers["attack"] + .25 * numbers["creation"]}],
                "keeper": {"gameplayer_id": None, "effective": None,
                           "ability": numbers["goalkeeping"]},
                "native_full_order_decoded": False}
    players = audit["players"]
    if not isinstance(players, list) or any(not isinstance(p, Mapping) for p in players):
        raise ValueError("actual penalty roster audit is invalid")
    starters = [p for p in players if p.get("is_starter") is True]
    if (len(starters) != 11 or {p.get("order") for p in starters} != set(range(11))
            or any(type(p.get("order")) is not int or type(p.get("roster_index")) is not int
                   or not 0 <= p["roster_index"] < 23 for p in starters)):
        raise ValueError("actual penalty shootout requires the exact eleven starters")
    takers = [_penalty_player(p, PENALTY_TAKER_FIELDS) for p in starters]
    identities = {(p["gameplayer_id"]["id"], p["gameplayer_id"]["serial"]) for p in takers}
    if len(identities) != 11 or len({p["roster_index"] for p in takers}) != 11:
        raise ValueError("actual penalty starters contain duplicate identities")
    contributions = audit.get("contributions")
    goalkeeping = contributions.get("goalkeeping", []) if isinstance(contributions, Mapping) else []
    if not isinstance(goalkeeping, list):
        raise ValueError("actual penalty goalkeeper audit is invalid")
    keeper_slots = [row.get("slot") for row in goalkeeping
                    if isinstance(row, Mapping) and row.get("role") == "GK"]
    if len(keeper_slots) != 1 or type(keeper_slots[0]) is not int or keeper_slots[0] not in range(11):
        raise ValueError("actual penalty goalkeeper must match the on-field GK role")
    keeper = _penalty_player(next(p for p in starters if p["order"] == keeper_slots[0]),
                             PENALTY_KEEPER_FIELDS)
    # No full native shootout sequence is decoded by this project. The known
    # native duty is one preferred kicker, match_plan_settings.set_piece_taker[5],
    # referenced by physical roster index. It leads only if still on the pitch.
    takers.sort(key=lambda p: (-p["ability"], p["order"]))
    plan = audit.get("penalty_plan", {})
    native_first = plan.get("native_first_taker_roster_index") if isinstance(plan, Mapping) else None
    preferred = next((p for p in takers if type(native_first) is int
                      and p["roster_index"] == native_first), None)
    if preferred is not None:
        takers.remove(preferred)
        takers.insert(0, preferred)
    return {"source": "actual_starting_xi", "takers": takers, "keeper": keeper,
            "native_first_taker_roster_index": native_first,
            "native_first_taker_used": preferred is not None,
            "native_full_order_decoded": False,
            "order_policy": ("valid on-field native PK duty first, then " if preferred else "")
                            + "actual effective penalty ability descending; entry slot breaks ties; "
                              "all eleven take once before cycling; simulator strategy, not a decoded native full order"}


def penalty_shootout(home_ratings, away_ratings, *, seed, model_version=MODEL_VERSION):
    """Five alternating kicks, early mathematical elimination, then sudden death.

    Coin toss randomly chooses the first side with the same probabilities.
    Real ratings audits use eleven actual starters, their effective finishing,
    set-piece, curl and kicking-power abilities, and the actual opposing GK.
    A known, valid on-field native PK duty goes first; otherwise (and for the
    rest) simulated penalty ability determines order, then actual entry slot.
    Numeric-only mathematical fixtures retain an explicitly labelled proxy.
    No fame, form boost, home effect, unused bench player or forced conversion.
    """
    _model_version(model_version)
    seed = _seed(seed)
    home, away = _ratings(home_ratings), _ratings(away_ratings)
    squads = [_penalty_squad(home_ratings, home), _penalty_squad(away_ratings, away)]
    rng = random.Random(seed)
    first = rng.randrange(2)
    order, score, taken, kicks = (first, 1 - first), [0, 0], [0, 0], []
    round_number = 0
    while True:
        round_number += 1
        for side in order:
            squad, opposing = squads[side], squads[1 - side]
            taker = squad["takers"][taken[side] % len(squad["takers"])]
            keeper = opposing["keeper"]
            probability, effect = _penalty_probability(taker["ability"], keeper["ability"])
            scored = rng.random() < probability
            taken[side] += 1
            score[side] += int(scored)
            kicks.append({"round": round_number,
                          "phase": "initial" if round_number <= 5 else "sudden_death",
                          "side": "home" if side == 0 else "away", "scored": scored,
                          "probability": probability, "ability_probability_effect": effect,
                          "taker": taker, "keeper": keeper,
                          "taker_source": squad["source"], "score": list(score)})
            if round_number <= 5:
                remaining = [5 - taken[0], 5 - taken[1]]
                if (score[0] > score[1] + remaining[1]
                        or score[1] > score[0] + remaining[0]):
                    return _shootout_result(seed, score, taken, kicks, round_number,
                                            first, squads,
                                            "early_elimination" if len(kicks) < 10 else "five_kicks")
        if taken[0] == taken[1] and round_number >= 5 and score[0] != score[1]:
            return _shootout_result(seed, score, taken, kicks, round_number,
                                    first, squads,
                                    "sudden_death" if round_number > 5 else "five_kicks")


def _shootout_result(seed, score, taken, kicks, rounds, first, squads, reason):
    schedules = [[_penalty_probability(taker["ability"], squads[1-side]["keeper"]["ability"])[0]
                  for taker in squad["takers"]] for side, squad in enumerate(squads)]
    return {"score": list(score), "winner": "home" if score[0] > score[1] else "away",
            "kicks": kicks, "rounds": rounds, "seed": seed,
            "model_version": MODEL_VERSION,
            "audit": {"first_side": "home" if first == 0 else "away",
                      "kicks_taken": list(taken), "ended_by": reason,
                      "probabilities": [schedule[0] for schedule in schedules],
                      "probability_schedules": schedules,
                      "squads": dict(zip(("home", "away"), squads)),
                      "base_probability": PENALTY_BASE,
                      "probability_effect_limit": PENALTY_EFFECT_LIMIT,
                      "taker_source": [squad["source"] for squad in squads],
                      "taker_ability_weights": dict(PENALTY_TAKER_FIELDS),
                      "keeper_ability_weights": dict(PENALTY_KEEPER_FIELDS),
                      "numeric_only_proxy": "0.75*attack + 0.25*creation; only when actual player audit is absent",
                      "source": PENALTY_RULES,
                      "calibration": "explicit design constants; not fitted penalty frequencies"}}


# Both spellings are public for call sites describing this as a simulation.
simulate_penalty_shootout = penalty_shootout
