"""Tournament-only progression presentation journal.

The owner calls capture/settle around rules.record + CPU advancement, inside
the SAME transaction that saves the tournament state and result receipt.
Nothing in this module writes a database, calls ai_division, grants rewards,
changes a match response, or opens a game UI on import.

Native windows require a separately verified game-thread presenter. The
original LEAGUE result flags alone cannot display them from an EVENT match.
Do not enable a presenter using this module's evidence inventory as a hook.
"""
import copy
import hashlib
import json

import tournament_rules as rules

REVISION = 'tournament-presentation-v1'
KEY = 'progression_presentation'
ENGINE_SHA256 = 'efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'

# Static control-flow evidence. The separately compiled homepage adapter now
# creates PROMOTED windows and returns native button/lifecycle receipts.
# creates AUCMenuAlertCreativeLeagueAM. STAYING/RELEGATED uses the other
# original dialog branch; it does not reverse the promotion animation.
NATIVE_EVIDENCE = {
    'engine_sha256': ENGINE_SHA256,
    'flag_parser_promoted_va': 0x75d25a0,
    'flag_parser_relegated_va': 0x75d26a0,
    'league_postmatch_selector_va': 0x7464f40,
    'league_main_create_alert_va': 0x33417f0,
    'promoted_branch_va': 0x3341c88,
    'promoted_factory_va': 0x333b1f0,
    'promoted_class_va': 0x3d82d3c,
    'native_child_factory_va': 0x302d514,
    'promoted_setup_va': 0x33401d4,
    'promoted_window': 'AUCMenuAlertCreativeLeagueAM',
    'promoted_widget': '/Game/Assets/ui/Data/Widget/General/Alert/AlertCreativeLeague/AlertCreativeLeague',
    'promoted_animation': 'FadeInAnimationStarted -> PlayFrameInProceed + PlayEffectAnim',
    'staying_relegated_branch_va': 0x3341880,
    'staying_relegated_window': '/Game/Assets/menu/dialog/AlertDialogNew/BP_MenuSimpleAlertDialogOneButton',
    'states': {'promoted': 4, 'staying_or_relegated': 5},
    'event_protocol_selects_league_ui': False,
    'event_presenter_installed': True,
    'event_presenter_instruction_verified': True,
    'native_event_presenter_ready': False,  # Device rendering still requires manual acceptance.
    'event_presenter_scope': 'PROMOTED windows only; elimination journal retained',
    'numbered_badges_suppressed': True,
    'display_selector_semantics': 'original Others effect only; no displayed or persisted league division',
    'device_validated': False,
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf8')).hexdigest()


def _identity(current):
    definition = current['definition']
    run = current['run_id']
    uid = definition['uuid']
    if not isinstance(run, str) or not run or not isinstance(uid, str) or not uid:
        raise ValueError('锦标赛届次身份缺失')
    return uid, run, definition['player_team_id']


def _event(current, stage_index, boundary, outcome, reason, fixture_ids):
    uid, run, player = _identity(current)
    stage = current['definition']['stages'][stage_index]
    # Legacy definitions without stage UUIDs retain a deterministic slot ID.
    # Difficulty, names, rqid, points and runtime definition revisions do NOT
    # participate in the event identity.
    stage_id = str(stage.get('uuid') or 'stage:' + str(stage_index))
    token = _digest([REVISION, uid, run, stage_id, boundary])
    return {'id': token, 'tournament_uuid': uid, 'run_id': run,
            'player_team_id': player, 'stage_index': stage_index,
            'stage_uuid': stage_id, 'boundary': boundary,
            'outcome': outcome, 'reason': reason,
            'animation': 'PROMOTED' if outcome in ('advanced', 'champion') else 'RELEGATED',
            'fixture_ids': sorted(fixture_ids)}


def resolved(current):
    """Read authoritative completed tables/ties; never infer from WIN/LOSE.

    Uses the rule engine's aggregate/away-goal/extra-time/PK decision. A loss
    in an unfinished table or first leg is not elimination. A second-leg
    loss can still be qualification. Byes generate no extra postmatch show.
    """
    _, _, player = _identity(current)
    stages = current['definition']['stages']
    fixtures = current['fixtures']
    events = {}
    for history in current.get('stage_history', []):
        index = history['stage']
        stage = stages[index]
        if stage['type'] not in ('groups', 'league'):
            continue
        own = next((table for table in history['tables']
                    if any(row['team'] == player for row in table)), None)
        if own is None:
            continue
        rank = next(i for i, row in enumerate(own) if row['team'] == player)
        direct = stage['advance_per_group']
        playoff = stage.get('playoff_per_group', 0)
        qualifies = rank < direct + playoff
        outcome = 'advanced' if qualifies else 'eliminated'
        reason = 'group_qualification' if stage['type'] == 'groups' else 'league_qualification'
        if not qualifies:
            reason = 'group_elimination' if stage['type'] == 'groups' else 'league_elimination'
        elif rank >= direct:
            reason = 'playoff_qualification'
        elif index == len(stages) - 1 and current.get('completed') and current.get('champion') == player:
            outcome, reason = 'champion', 'champion'
        event = _event(current, index, 'table', outcome, reason,
                       [f['id'] for f in fixtures if f['stage'] == index and player in (f['home'], f['away'])])
        events[event['id']] = event
    ties = {}
    for fixture in fixtures:
        if fixture.get('tie') is not None and player in (fixture['home'], fixture['away']):
            ties.setdefault((fixture['stage'], fixture['tie']), []).append(fixture)
    for (index, tie), rows in ties.items():
        if any(row.get('bye') for row in rows):
            continue
        winner = rules.tie_winner(rows)
        if winner is None:
            continue
        stage = stages[index]
        if winner != player:
            outcome, reason = 'eliminated', 'knockout_elimination'
        else:
            outcome = 'advanced'
            reason = 'playoff_win' if stage['type'] == 'playoff' else 'knockout_next_round'
            # The final tie is identified from its ROUND's participants, not
            # from the last stored fixture or the local match's WIN flag.
            participants = {t for f in fixtures if f['stage'] == index and f['round'] == rows[0]['round']
                            for t in (f['home'], f['away']) if t is not None}
            if index == len(stages) - 1 and len(participants) == 2 and current.get('completed') and current.get('champion') == player:
                outcome, reason = 'champion', 'champion'
        event = _event(current, index, 'tie:' + str(tie), outcome, reason,
                       [row['id'] for row in rows])
        events[event['id']] = event
    return events


def capture(current):
    """Read-only baseline before settlement or CPU advancement."""
    uid, run, _ = _identity(current)
    return {'revision': REVISION, 'tournament_uuid': uid, 'run_id': run,
            'resolved': resolved(current)}


def _journal(current):
    uid, run, _ = _identity(current)
    journal = current.get(KEY)
    if journal is None:
        journal = {'revision': REVISION, 'tournament_uuid': uid, 'run_id': run,
                   'events': [], 'delivery': None}
        current[KEY] = journal
    if (journal.get('revision') != REVISION or journal.get('tournament_uuid') != uid
            or journal.get('run_id') != run):
        raise ValueError('锦标赛演出记录与当前届次不一致')
    return journal


def settle(current, before, game_id=None):
    """Append new decisions only; save current atomically with match receipt.

    Re-evaluating the same transition is idempotent. Starting on an existing
    save does not replay historical decisions: capture it before new work.
    A run mismatch raises, so a reply from a previous edition cannot insert
    a presentation into a freshly registered tournament.
    """
    uid, run, _ = _identity(current)
    if (before.get('revision') != REVISION or before.get('tournament_uuid') != uid
            or before.get('run_id') != run):
        raise ValueError('锦标赛结算演出基线不属于本届赛事')
    decisions = resolved(current)
    previous = before['resolved']
    journal = _journal(current)
    existing = {event['id']: event for event in journal['events']}
    added = []
    for ident, decision in decisions.items():
        if ident in previous:
            if previous[ident] != decision:
                raise ValueError('已决出的晋级结果发生变化')
            continue
        if ident in existing:
            recorded = {key: existing[ident][key] for key in decision}
            if recorded != decision:
                raise ValueError('晋级演出事件身份冲突')
            continue
        event = copy.deepcopy(decision)
        event.update(status='pending', game_id=None if game_id is None else str(game_id))
        added.append(event)
    added.sort(key=lambda event: (event['stage_index'], max(event['fixture_ids'], default=0), event['id']))
    journal['events'].extend(added)
    return copy.deepcopy(added)


def pending(current):
    """Return the oldest unconfirmed decision, without mutating state."""
    journal = current.get(KEY)
    if journal is None:
        return None
    uid, run, _ = _identity(current)
    if journal.get('revision') != REVISION or journal.get('tournament_uuid') != uid or journal.get('run_id') != run:
        raise ValueError('锦标赛演出记录与当前届次不一致')
    row = next((event for event in journal['events'] if event['status'] != 'confirmed'), None)
    return copy.deepcopy(row)


def begin(current, session_id):
    """Lease a native window once per menu session; retain until confirmation.

    Commit this lease before dispatch. Native dispatch must also deduplicate
    event ID. After process/menu recovery a new session may resume the same
    UNCONFIRMED window, with the same stable event ID. Neither GET/result
    retries nor rqid changes create another window in one session.
    """
    if not isinstance(session_id, str) or not 1 <= len(session_id) <= 128:
        raise ValueError('演出会话身份无效')
    row = pending(current)
    if row is None:
        return None
    journal = _journal(current)
    delivery = journal.get('delivery')
    if delivery and delivery['event_id'] == row['id'] and delivery['session_id'] == session_id:
        return None
    delivery = {'event_id': row['id'], 'session_id': session_id,
                'token': _digest([REVISION, row['id'], session_id])}
    journal['delivery'] = delivery
    next(event for event in journal['events'] if event['id'] == row['id'])['status'] = 'presenting'
    return {'event': row, 'delivery': copy.deepcopy(delivery), 'view': view(current, row)}


def release(current, event_id, token):
    """Verified dispatch failure: retry later; a created window is not failure."""
    if current.get(KEY) is None:
        return False
    journal = _journal(current)
    delivery = journal.get('delivery')
    if not delivery or delivery['event_id'] != event_id or delivery['token'] != token:
        return False
    row = next((row for row in journal['events'] if row['id'] == event_id), None)
    if row is None or row['status'] == 'confirmed':
        return False
    row['status'] = 'pending'
    journal['delivery'] = None
    return True


def confirm(current, event_id, token):
    """Call only from a verified user-confirm callback, never result success.

    An old session's completion cannot consume the recovered/new window.
    Confirm retries are idempotent. Persist before allowing the next window.
    """
    if current.get(KEY) is None:
        return False
    journal = _journal(current)
    row = next((row for row in journal['events'] if row['id'] == event_id), None)
    if row is None:
        return False
    if row['status'] == 'confirmed':
        return row.get('confirmed_token') == token
    delivery = journal.get('delivery')
    if not delivery or delivery['event_id'] != event_id or delivery['token'] != token:
        return False
    row.update(status='confirmed', confirmed_token=token)
    journal['delivery'] = None
    return True


def view(current, event):
    """Presentation-only text. No difficulty or fictitious division changes."""
    uid, run, _ = _identity(current)
    if event['tournament_uuid'] != uid or event['run_id'] != run:
        raise ValueError('演出不属于当前锦标赛')
    names = {'group_qualification': '小组出线', 'league_qualification': '联赛晋级',
             'playoff_qualification': '进入附加赛', 'playoff_win': '附加赛胜出',
             'knockout_next_round': '晋级下一轮', 'group_elimination': '小组赛淘汰',
             'league_elimination': '联赛淘汰', 'knockout_elimination': '本届赛事淘汰',
             'champion': '夺得冠军'}
    return {'title': names[event['reason']], 'body': current['definition']['name'],
            'confirm_text': '确认', 'native_presentation': event['animation'],
            'event_id': event['id'], 'run_id': run}


class NativePresenterUnavailable(RuntimeError):
    pass


def dispatch(current, session_id, presenter=None):
    """Fail closed until a game-thread/confirmation adapter is supplied.

    This function intentionally does not begin a lease when no verified
    presenter exists. Never set league_info flags as a fallback.
    Integrators should use begin/confirm directly around their DB commits;
    this convenience entry point supports a synchronous, atomic test host.
    """
    if pending(current) is None:
        return False
    if presenter is None or getattr(presenter, 'revision', None) != REVISION or not getattr(presenter, 'native_verified', False):
        raise NativePresenterUnavailable('锦标赛原生升降级演出桥尚未接入并核验；待确认事件已保留')
    offer = begin(current, session_id)
    if offer is None:
        return False
    try:
        accepted = presenter.show(copy.deepcopy(offer))
    except Exception:
        # A throwing UI host may already have created the window. Retain
        # the lease; only an explicit verified rejection allows retry.
        raise
    if accepted is False:
        release(current, offer['event']['id'], offer['delivery']['token'])
    return accepted is True
