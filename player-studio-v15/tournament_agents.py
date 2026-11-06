"""Native Contract chance deals backed exclusively by tournament run ledgers.

No agent is inserted into the ordinary managed pool, and no player is granted
to gameplayers. The native count field holds earned chances; paid price lists
are empty. All dispatch is intercepted before the stock permanent-grant path.
"""
import copy
import hashlib
import json

import tournament_rewards as rewards

NAME = '锦标赛特殊机会抽取'
REGISTRY = 'player_studio_tournament_chance_agents_v1'
START, STOP = 1500000000, 1600000000
DRAW = 'CMD_USE_MYCLUB_AGENT'
LIST = 'CMD_GET_MYCLUB_AGENTLIST'
CARDS = 'CMD_GET_MYCLUB_PROCURABLE_GAMEPLAYERLIST'
BOX = 'CMD_GET_MYCLUB_AGENT_BOX_INFO'
RESET = 'CMD_RESET_MYCLUB_AGENT'
COMMANDS = {DRAW, CARDS, BOX, RESET}


def _get(conn, key, default=None):
    row = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else copy.deepcopy(default)


def _put(conn, key, value):
    conn.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (key, json.dumps(value, ensure_ascii=False, separators=(',', ':'))))


def entries(service, conn, occupied=()):
    """Stable IDs distinguish editions, clubs and even delayed old requests.

    Merely viewing Contracts never enrolls a team or starts/resets a run.
    An edited definition exposes a fresh, zero-chance deal until re-entry.
    """
    from tournament_runtime import PREFIX, progress_signature
    registry = _get(conn, REGISTRY, {})
    before = copy.deepcopy(registry)
    used = set(registry.values()) | {int(i) for i in occupied}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='agents'").fetchone():
        used.update(int(r[0]) for r in conn.execute('SELECT agent_id FROM agents'))
    result = []
    for definition in service.definitions():
        current = _get(conn, PREFIX + definition['uuid'])
        signature = progress_signature(definition)
        if current and progress_signature(current['definition']) != signature:
            current = None
        edition = current['run_id'] if current else 'pending:' + signature
        token = hashlib.sha256(json.dumps([definition['uuid'], edition, definition['player_team_id']],
                                          separators=(',', ':')).encode()).hexdigest()
        aid = registry.get(token)
        if aid is None:
            aid = START + int(token[:16], 16) % (STOP - START)
            while aid in used:
                aid = START + (aid - START + 1) % (STOP - START)
            registry[token] = aid;used.add(aid)
        result.append({'agent_id':aid, 'definition':definition, 'current':current})
    if registry != before:
        _put(conn, REGISTRY, registry)
    return result


def cards(service, conn, entry):
    rows, report = rewards.available(conn, service.document())
    report = dict(report, base_player_count=buckets(rows), base_player_total=len(rows))
    current = entry['current']
    consumed = set(rewards.rental_ids(current)) if current else set()
    result = []
    for row in rows:
        if int(row['gameplayer_id']['id']) in consumed:
            continue
        from tournament_rules import seed_number
        seed = current['seed'] if current else entry['definition']['uuid']
        player = copy.deepcopy(service.generator.rental_prepared(row,seed_number(seed,row['gameplayer_id']['id'],'rental-reinforcement-booster')))
        player.update(gameplayer_id={'id':int(row['gameplayer_id']['id']), 'serial':0},
                      type='RENTAL', rental_match_left=99,
                      initial_base_team_id=entry['definition']['player_team_id'])
        nation = service.document().get('tournament_national_team_nations', {}).get(str(entry['definition']['player_team_id']))
        if nation is not None:
            player.update(_nation_id=nation, initial_base_national_team_id=entry['definition']['player_team_id'])
        player['parameters'] = player['parameters'][:147]
        result.append(player)
    return result, report


def buckets(rows):
    counts = [0] * 5
    for player in rows:
        rarity = max(1, min(5, int(player.get('default_rarity') or 5)))
        counts[rarity - 1] += 1
    return counts


def agent(service, conn, entry, template):
    from tournament_runtime import team_name
    definition, current = entry['definition'], entry['current']
    pool, report = cards(service, conn, entry)
    remaining = rewards.status(current)['available'] if current else 0
    club = team_name(definition['player_team_id'], service.names())
    row = copy.deepcopy(template)
    row.update(agent_id=entry['agent_id'], title=NAME,
               subcategory=definition['name'] + ' · ' + club + ' · 可用机会 ' + str(remaining) + ' 次',
               count=remaining, target_level=1, start_date=0, expiration_date=0,
               can_reset='NO', limit_count=0, use_count=0, reset_time=0,
               agent_type='BOX_AGENT', advertising_id='', kind_list=['NONE'],
               agent_rarity_type='AGENT_NONE', agent_early_release_type='NOT_EARLY_RELEASE',
               description='仅通过本锦标赛阶段晋级获得抽取机会，不可使用金币或 GP。抽出的球员仅在「' + definition['name']
                           + '」本届赛事中视为' + club + '租借球员，赛事结束离队，不影响其他模式。',
               note_text='晋级获得机会。抽取后重新打开比赛计划，使用本届租借球员。',
               player_list_total=report['base_player_total'], remaining_player_count=buckets(pool),
               base_player_count=report['base_player_count'], acquired_list=[],
               pickup_list=pool[:4], banner_a_pickup_list=pool[:3], banner_c_pickup_list=pool[:3],
               pickup_cardtype_list=[p['gameplayer_id'].copy() for p in pool[:4]],
               probability=format(100 / len(pool), '.4f') if pool else '0',
               confirmed_probability='0', player_rate_list=[])
    # Reuse packaged tournament artwork, never an unrelated sale's banner.
    image = service.document().get('tournament_entry_images', {})
    from tournament_runtime import cover_image
    image = cover_image(definition, image.get('landscape') or service.document().get('tournament_entry_image'))
    if image:
        row.update(banner_file_c_name=image, banner_file_d_name=image)
    return row


def template(logic, response=None):
    candidates = [response or {}, logic.responses.get(LIST) or {}, logic.templates.get(LIST) or {}]
    for candidate in candidates:
        row = next((r for r in candidate.get('agent_list', []) if isinstance(r, dict)), None)
        if row is not None:
            return row
    raise ValueError('原生合约卡池模板缺失')


def decorate(service, logic, response):
    """Append only this feature's native deals; never change ordinary pools."""
    if response.get('result') != 'NOERR':
        return response
    conn = logic.conn
    registry = _get(conn, REGISTRY, {})
    stale_ids = set(registry.values())
    rows = [r for r in response.get('agent_list', []) if int(r['agent_id']) not in stale_ids]
    deals = entries(service, conn, [r['agent_id'] for r in rows])
    if not deals:
        response['agent_list'] = rows
        response['agent_price_list'] = [r for r in response.get('agent_price_list', []) if int(r['agent_id']) not in stale_ids]
        return response
    base = template(logic, response)
    response['agent_list'] = rows + [agent(service, conn, e, base) for e in deals]
    prices = [r for r in response.get('agent_price_list', []) if int(r['agent_id']) not in stale_ids]
    # No coin/GP options: native agent.count is the only payment method.
    response['agent_price_list'] = prices + [dict(agent_id=e['agent_id'], discount_limit_count=0,
                                                discount_use_count=0, price_list=[]) for e in deals]
    return response


def request_key(request):
    values = [request.get('user_id'), request.get('rqid')]
    if any(type(v) not in (str, int) or not str(v) or len(str(v)) > 96 for v in values):
        raise ValueError('锦标赛抽取请求缺少有效身份编号')
    return hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()


def handle(service, logic, command, request, original):
    """Return None only for unrelated requests; obsolete own IDs fail closed."""
    if command not in COMMANDS:
        return None
    raw = request.get('agent_id')
    if type(raw) not in (str, int):
        return None
    try:aid = int(raw)
    except ValueError:return None
    conn = logic.conn;registry = _get(conn, REGISTRY, {})
    if aid not in registry.values():
        if START <= aid < STOP and not conn.execute('SELECT 1 FROM agents WHERE agent_id=?',(aid,)).fetchone():
            raise ValueError('该锦标赛卡池尚未登记，请重新打开合约')
        return None
    entry = next((e for e in entries(service, conn) if e['agent_id'] == aid), None)
    if entry is None:
        raise ValueError('该抽取机会不属于当前锦标赛届次，请重新打开合约')
    current = entry['current']
    if command == RESET:
        raise ValueError('锦标赛特殊机会抽取不可重置，只能通过锦标赛晋级获得机会')
    base = copy.deepcopy(logic.responses.get(command) or logic.templates.get(command) or {})
    base.update(result='NOERR', msgid=command, rqid=request.get('rqid'))
    if command == CARDS:
        pool, _ = cards(service, conn, entry)
        base.update(gameplayer_list=[dict(gameplayer=p, is_dummy='NO') for p in pool], acquired_player_list=[])
        return base
    if command == BOX:
        pool, report = cards(service, conn, entry)
        base.update(remaining_player_count=buckets(pool), base_player_count=report['base_player_count'], can_reset='NO')
        return base
    count=request.get('count',1)
    if type(count) is not int or not 1<=count<=10:
        raise ValueError('锦标赛特殊机会抽取每次最多 10 张')
    if request.get('payment_kind') not in (None, 'AGENT', 'PAYMENT_KIND_AGENT'):
        raise ValueError('该卡池只能使用锦标赛获得的抽取机会')
    if current is None or current.get('completed'):
        raise ValueError('只有晋级中的锦标赛可以获得并使用本届抽取机会')
    if current.get('active', {}).get('started'):
        raise ValueError('请先结束当前比赛，再到合约使用锦标赛抽取机会')
    key = request_key(request)
    receipt = current.get(rewards.KEY, {}).get('draw_receipts', {}).get(key)
    if receipt and receipt.get('requested_count',receipt.get('count',1))!=count:
        raise ValueError('抽取重试数量与原请求不一致')
    if receipt and receipt.get('native_reply'):
        result = copy.deepcopy(receipt['native_reply']);result['rqid'] = request.get('rqid')
        return result
    stock = original(logic, LIST, request)
    if stock.get('result') != 'NOERR':
        raise ValueError('原生合约列表尚未就绪，未消耗抽取机会')
    result = rewards.draw(current, conn, service.document(), key, service.generator,count=count)
    pool={int(p['gameplayer_id']['id']):p for p in service.reinforcements(conn, entry['definition'], current)}
    players=[pool[loan['card_id']]for loan in result.get('loans',[result.get('loan')])]
    # Display through the stock draw scene but never call draw_and_grant,
    # add_player or a global owned-list projection.
    import draw_presentation
    base.update(gameplayer_list=[dict(gameplayer=p, is_dummy='NO', is_warehouse='NO')for p in players], draft_list=[])
    base.update(draw_presentation.response_fields(players))
    from personal_runtime import sanitize_draw_effects
    sanitize_draw_effects(base, service.document())
    base = logic._currency(base)
    entry['current'] = current
    # Keep all other deals intact; refresh counts after the spend.
    # The active tournament state must already be visible to the projection,
    # in the same outer transaction. Any serialization failure rolls it back.
    from tournament_runtime import PREFIX
    _put(conn, PREFIX + entry['definition']['uuid'], current)
    stock.update(result='NOERR')
    decorate(service, logic, stock)
    updated = next(r for r in stock['agent_list'] if r['agent_id']==aid)
    base.update(agent_list=stock['agent_list'], agent_price_list=stock['agent_price_list'],
                remaining_player_count=updated['remaining_player_count'], base_player_count=updated['base_player_count'])
    current[rewards.KEY]['draw_receipts'][key]['native_reply'] = copy.deepcopy(base)
    _put(conn, PREFIX + entry['definition']['uuid'], current)
    return base
