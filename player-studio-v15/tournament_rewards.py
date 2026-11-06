"""Tournament reinforcement pool and run-scoped rental ledger.

The reference table is an allowlist, never a source of invented game stats.
No owned-player/coach table is written here. Callers persist the returned
ledger in the same transaction as the tournament receipt.
"""
import copy
import hashlib
import json
from pathlib import Path
import random
import sys

_EMBEDDED_POOL = None
POOL_FILE = 'tournament-reinforcements.json'
KEY = 'reinforcements'
EXCLUDED_IDS = {89138556678270}


def validate_catalogue(value):
    if not isinstance(value, dict) or value.get('format') != 'player-studio-tournament-reinforcements' or value.get('version') != 1:
        raise ValueError('锦标赛补强卡池格式不支持')
    cards = value.get('cards')
    if not isinstance(cards, list) or not cards:
        raise ValueError('锦标赛补强卡池为空')
    if any(not isinstance(row, dict) or 'card_id' not in row for row in cards):
        raise ValueError('锦标赛补强卡池记录不完整')
    ids = [row['card_id'] for row in cards]
    if any(type(cid) is not int or cid <= 0 for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError('锦标赛补强卡池存在重复或无效编号')
    if EXCLUDED_IDS.intersection(ids):
        raise ValueError('锦标赛补强卡池包含已指定移除的姆巴佩卡')
    return value


def catalogue():
    value = copy.deepcopy(_EMBEDDED_POOL) if _EMBEDDED_POOL is not None else json.loads(
        (Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'resources' / POOL_FILE).read_text('utf8'))
    return validate_catalogue(value)


def runtime_source(source=None, resources=None):
    """Embed the same checked pool in PC/Android generated game helpers."""
    source = source if source is not None else Path(__file__).read_text('utf8')
    value = json.loads((Path(resources) / POOL_FILE).read_text('utf8')) if resources else catalogue()
    marker = '_EMBEDDED_POOL = None\n'
    if source.count(marker) != 1:
        raise ValueError('锦标赛补强卡池嵌入点改变')
    validate_catalogue(value)
    return source.replace(marker, '_EMBEDDED_POOL = ' + repr(value) + '\n', 1)


def available(conn, document, generator=None):
    """Resolve exact IDs in the *current* installed catalogue, not V22 names."""
    from division_squads import native_card_ids
    value = catalogue();valid = native_card_ids(document)
    recycled = {str(row['id']) for row in document.get('catalogue_recycle_bin', [])}
    present, missing, unusable = [], [], []
    for item in value['cards']:
        cid = item['card_id']
        row = conn.execute('SELECT fingerprint,payload FROM managed_cards WHERE card_id=?', (str(cid),)).fetchone()
        # Some installed special-event cards are intentionally absent from
        # the ordinary Contract catalogue. Keep an exact, export-validated
        # tournament-only definition instead of relaxing that global filter.
        if not row:
            payload = document.get('tournament_reinforcement_cards', {}).get(str(cid))
            if payload is not None:
                raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
                row = (hashlib.sha256(raw.encode()).hexdigest(), raw)
        if not row or str(cid) in recycled or valid is not None and cid not in valid:
            missing.append(cid);continue
        try:
            card = json.loads(row[1]);params = card['parameters']
            if int(card['gameplayer_id']['id']) != cid or len(params) != 147 or any(type(n) is not int for n in params):
                raise ValueError('卡牌布局异常')
            card['_studio_fingerprint'] = row[0] or hashlib.sha256(row[1].encode()).hexdigest()
            # The ordinary shared trainer computes the real level cap and
            # development; reference_overall/max_level never become abilities.
            if generator is not None:generator.prepared(card)
            present.append(card)
        except (ValueError, KeyError, TypeError):
            unusable.append(cid)
    return present, {'revision':value['revision'],'source_sha256':value['source_sha256'],
                     'listed':len(value['cards']),'available':len(present),
                     'missing_ids':missing,'unusable_ids':unusable,
                     'excluded_card_ids':sorted(EXCLUDED_IDS)}


def export_catalogue(library, document, inherited=None):
    """Copy real installed wire definitions; never synthesize reference stats."""
    from contextlib import closing
    from division_squads import native_card_ids
    valid = native_card_ids(document)
    recycled = {str(row['id']) for row in document.get('catalogue_recycle_bin', [])}
    result = {}
    with closing(library.db()) as conn:
        for item in catalogue()['cards']:
            cid = str(item['card_id'])
            if cid in recycled or valid is not None and int(cid) not in valid:
                continue
            row = conn.execute('SELECT payload FROM players WHERE id=?', (cid,)).fetchone()
            payload = json.loads(row[0]) if row else copy.deepcopy((inherited or {}).get(cid))
            if payload is None:
                continue
            params = payload.get('parameters')
            if (int(payload.get('gameplayer_id', {}).get('id', 0)) != int(cid)
                or not isinstance(params, list) or len(params) != 147
                or any(type(n) is not int for n in params)):
                raise ValueError('锦标赛特殊机会抽取球员资料无效：' + cid)
            result[cid] = payload
    return result


def chances(wins, played):
    if type(wins) is not int or type(played) is not int or not 0 <= wins <= played or played == 0:
        raise ValueError('阶段胜率缺少有效比赛记录')
    return max(1, (wins * 10 + played - 1) // played)


def _ledger(current):
    ledger = current.setdefault(KEY, {'version':1,'run_id':current['run_id'],
                                     'awards':{},'rentals':[],'draw_receipts':{}})
    if ledger.get('version') != 1 or ledger.get('run_id') != current['run_id']:
        raise ValueError('补强记录不属于本届锦标赛')
    return ledger


def settle(current, decisions):
    """Award only a completed stage followed by actual qualification.

    A knockout tie advancing within the same stage does not grant an extra
    award. No historical award is reconstructed when loading an old save.
    """
    ledger = _ledger(current);player = current['definition']['player_team_id'];added = []
    for event in decisions:
        index = event['stage_index']
        if event['outcome'] != 'advanced' or index >= current['stage_index']:
            continue
        stage = current['definition']['stages'][index]
        stage_id = stage.get('uuid') or str(index)
        if stage_id in ledger['awards']:continue
        rows = [f for f in current['fixtures'] if f['stage'] == index and not f.get('bye')
                and player in (f['home'], f['away'])]
        if not rows or any(not f['played'] for f in rows):continue
        wins = 0
        for f in rows:
            side = int(f['away'] == player);score = f['score']
            wins += int(score[side] > score[1-side] or score[side] == score[1-side]
                        and isinstance(f.get('penalties'), list) and f['penalties'][side] > f['penalties'][1-side])
        award = {'stage_index':index,'stage_uuid':stage_id,'wins':wins,'played':len(rows),
                 'granted':chances(wins,len(rows)),'used':0,'notified':False,
                 'message':'由于已晋级下一阶段，可以补强球队了！'}
        ledger['awards'][stage_id] = award;added.append(copy.deepcopy(award))
    if current.get('completed'):
        # History/receipts survive; live loans and unspent chances depart.
        ledger['rentals'] = [];ledger['closed'] = True
    return added


def status(current):
    ledger = current.get(KEY) or {};closed = current.get('completed') or ledger.get('closed')
    awards = list(ledger.get('awards', {}).values())
    return {'available':0 if closed else sum(a['granted']-a['used'] for a in awards),
            'rentals':[] if closed else copy.deepcopy(ledger.get('rentals', [])),
            'awards':copy.deepcopy(awards),'closed':bool(closed)}


def draw(current, conn, document, request_id, generator=None, rng=None, count=1):
    """Idempotent draw of up to ten cards, persisted by the caller's transaction.

    Identity stays the native card ID/serial 0, as required by the native
    rental registry. Repeated draws of a card already rented are excluded.
    The tournament's represented club is metadata on this loan only.
    """
    if not isinstance(request_id,str) or not 1 <= len(request_id) <= 128:
        raise ValueError('补强抽取缺少有效请求编号')
    if type(count) is not int or not 1<=count<=10:
        raise ValueError('锦标赛特殊机会抽取每次最多 10 张')
    ledger = _ledger(current)
    if current.get('completed') or ledger.get('closed'):raise ValueError('本届锦标赛已结束，租借球员已离队')
    receipt = ledger['draw_receipts'].get(request_id)
    if receipt:
        if receipt.get('requested_count',receipt.get('count',1)) != count:raise ValueError('抽取重试数量与原请求不一致')
        return copy.deepcopy(receipt)
    balance=status(current)['available']
    if balance < 1:
        raise ValueError('锦标赛补强抽取机会不足，未消耗机会')
    cards, report = available(conn, document, generator)
    used = {r['card_id'] for r in ledger['rentals']}
    cards = [card for card in cards if int(card['gameplayer_id']['id']) not in used]
    if not cards:raise ValueError('当前游戏库可抽取的补强卡不足，未消耗机会')
    requested=count;count=min(count,balance,len(cards))
    # Validate the entire batch before spending anything. Work on a private
    # ledger so even RNG/preparation failure cannot leave a partial ten-draw.
    selected = (rng or random.SystemRandom()).sample(cards,count)
    updated=copy.deepcopy(ledger);loans=[]
    for card in selected:
        award=next(a for a in updated['awards'].values() if a['used']<a['granted'])
        loan={'card_id':int(card['gameplayer_id']['id']),
              'tournament_uuid':current['definition']['uuid'],'run_id':current['run_id'],
              'team_id':current['definition']['player_team_id'],'award_stage_uuid':award['stage_uuid']}
        updated['rentals'].append(loan);award['used']+=1;loans.append(copy.deepcopy(loan))
    result={'requested_count':requested,'count':count,'loans':loans,'remaining':balance-count,'pool':report}
    if count==1:result['loan']=copy.deepcopy(loans[0])
    updated['draw_receipts'][request_id]=copy.deepcopy(result)
    current[KEY]=updated
    return result


def rental_ids(current):
    return [r['card_id'] for r in status(current)['rentals']]
