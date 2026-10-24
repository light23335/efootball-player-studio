"""Local pack projects and compilation to the game's managed-card pools."""
from pathlib import Path
import copy,hashlib,json,os,re,secrets,sqlite3,uuid
from contextlib import closing
from pack_catalogue import exclusions
from native_celebration import restore_payload

def random_options(resources):
    """Only offer real cards that can pass the same native pack compiler."""
    pools=_random_pools(resources)
    return [{'card_type':kind,'available':len(rows)} for kind,rows in pools.items()]

def _random_pools(resources):
    pools={};blocked=exclusions(resources)
    with closing(sqlite3.connect('file:'+str((Path(resources)/'library.sqlite3').resolve())+'?mode=ro',uri=True)) as db:
        for pid,name,kind,payload in db.execute('select id,name,card_type,payload from players order by card_type,id'):
            p=json.loads(payload);params=p.get('parameters',[])
            if pid in blocked or len(params)<=47 or not params[47]:continue
            pools.setdefault(kind,[]).append({'kind':'original','id':str(pid),'name':name+' · '+kind,'weight':1})
    return pools

def random_members(resources,request):
    """Choose distinct cards without editing the pack until the user saves."""
    quotas=request.get('quotas');existing=request.get('members',[])
    if not isinstance(quotas,list) or not quotas or not isinstance(existing,list):raise ValueError('请选择卡种和数量')
    if len(existing)>2000:raise ValueError('每个卡包最多 2000 名球员')
    excluded={str(m.get('id')) for m in existing if m.get('kind')=='original'}
    pools=_random_pools(resources);plan=[];seen=set();total=0
    for quota in quotas:
        kind=quota.get('card_type');count=quota.get('count')
        if kind not in pools or kind in seen:raise ValueError('卡种不存在或重复')
        if type(count) is not int or not 0<=count<=2000:raise ValueError('随机添加数量须为 0–2000 的整数')
        seen.add(kind);total+=count
        candidates=[r for r in pools[kind] if r['id'] not in excluded]
        if count>len(candidates):raise ValueError(f'{kind} 可添加 {len(candidates)} 张（已排除卡池中已有卡片），请减少数量')
        plan.append((candidates,count))
    if not total:raise ValueError('请至少填写一种卡的数量')
    if len(existing)+total>2000:raise ValueError(f'卡包最多 2000 张，当前还能添加 {2000-len(existing)} 张')
    rng=secrets.SystemRandom()
    return {'rows':[row for candidates,count in plan for row in rng.sample(candidates,count)],'count':total}

def normalize(value):
    p=copy.deepcopy(value)
    p['uuid']=str(uuid.UUID(p.get('uuid') or str(uuid.uuid4())))
    p['name']=str(p.get('name') or '').strip()[:80]
    if not p['name']:raise ValueError('请填写卡包名称')
    p['enabled']=bool(p.get('enabled',True));p['replacement']=bool(p.get('replacement',False))
    p['description']=str(p.get('description') or '')[:500]
    p['banner']=int(p.get('banner',0))
    from pack_covers import normalize as normalize_cover
    p['cover']=normalize_cover(p.get('cover'))
    members=p.get('members',[])
    if not isinstance(members,list) or not 0<=len(members)<=2000:raise ValueError('每个卡包最多 2000 名球员；空卡包可保存为草稿')
    seen=set()
    for row in members:
        if row.get('kind')=='custom':key=str(uuid.UUID(row['id']))
        elif row.get('kind')=='original' and re.fullmatch(r'[0-9]{1,16}',str(row.get('id'))):key=str(int(row['id']))
        else:raise ValueError('卡包成员身份无效')
        pair=(row['kind'],key)
        if pair in seen:raise ValueError('卡包成员重复，请调整权重代替重复添加')
        seen.add(pair);row['id']=key
        if type(row.get('weight')) is not int or not 1<=row['weight']<=10000:raise ValueError('抽取权重范围为整数 1–10000')
        row['name']=str(row.get('name') or key)[:80]
    return p

def load(store):
    path=store.root/'packs.json'
    if not path.exists():return []
    return [normalize(p) for p in json.loads(path.read_text(encoding='utf8'))]

def save(store,pack):
    p=normalize(pack)
    if p.get('cover') and not (store.root/'assets'/p['cover']['asset_id']).is_file():raise ValueError('卡包封面文件不存在，请重新导入')
    with store.lock:
        rows=[r for r in load(store) if r['uuid']!=p['uuid']]+[p]
        path=store.root/'packs.json'
        if path.exists():
            (store.root/'backups'/('packs-'+uuid.uuid4().hex+'.json')).write_bytes(path.read_bytes())
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temp,path)
    return {'pack':p,'rows':rows}

def compile_packs(packs,definitions,resources,cover_bindings=None,excluded=None):
    template=json.loads((resources/'native-pack-template.json').read_text(encoding='utf8'))
    custom={d['identity']['package_id']:d for d in definitions};out=[];used=set()
    blocked=exclusions(resources) if excluded is None else excluded
    with closing(sqlite3.connect(resources/'library.sqlite3')) as db:
        for pack in packs:
            p=normalize(pack);aid=100000+int(hashlib.sha256(p['uuid'].encode()).hexdigest()[:8],16)%1000000000
            if aid in used:raise ValueError('卡包编号冲突，请复制为新卡包后重试')
            used.add(aid);members=[];skipped=[]
            if not p['members']:raise ValueError(p['name']+'：卡包是空草稿，请先添加球员后再生成 APK')
            for row in p['members']:
                if row['kind']=='original' and row['id'] in blocked:
                    skipped.append({'card_id':row['id'],**blocked[row['id']]});continue
                if row['kind']=='custom':
                    if row['id'] not in custom:raise ValueError(p['name']+'：请在实装页勾选卡包中的自建球员 '+row['name'])
                    d=custom[row['id']];payload=copy.deepcopy(d['owned']);cid=d['identity']['card_id']
                    payload['gameplayer_id']={'id':cid,'serial':0};payload['parameters']=d['base_parameters']
                    payload['level_info'].update(level=1,exp_total=0,exp_current_level=0,customize_point=0)
                    kind,subtype=d['card_type'],d['card_series']
                else:
                    result=db.execute('select payload,card_type from players where id=?',(row['id'],)).fetchone()
                    if not result:raise ValueError('卡包球员不在原库：'+row['id'])
                    payload=restore_payload(json.loads(result[0]));cid=int(row['id']);kind,subtype=result[1],''
                    if not payload['parameters'][47]:raise ValueError('卡包包含空占位球员：'+row['name'])
                members.append({'card_id':str(cid),'weight':row['weight'],'payload':payload,'card_type':kind,'subtype':subtype})
            if not members:raise ValueError(p['name']+'：没有可用球员，所选成员均被当前游戏版本禁用，请重新选择卡片')
            if p.get('cover'):
                banner=(cover_bindings or {}).get(p['uuid'])
                if not banner:raise ValueError(p['name']+'：自选封面尚未编译')
            else:
                if not 0<=p['banner']<len(template['banners']):raise ValueError('卡包封面预设不存在')
                banner=template['banners'][p['banner']]
            agent=copy.deepcopy(template['agent'])
            agent.update(agent_id=aid,title=p['name'],subcategory='个人卡包',description=p['description'],note_text='个人离线学习卡包 · 免费抽取',
                         start_date=0,expiration_date=2147483647,use_count=0,limit_count=0,
                         banner_file_c_name=banner['c'],banner_file_d_name=banner['d'],pickup_list=[],banner_a_pickup_list=[],banner_c_pickup_list=[],pickup_cardtype_list=[])
            price=copy.deepcopy(template['price']);price['agent_id']=aid
            for option in price['price_list']:
                option['price'].update(coin_price=0,coin_price_base=0,gp_price=0,gp_price_base=0)
            out.append({'uuid':p['uuid'],'agent_id':aid,'name':p['name'],'enabled':p['enabled'],'replacement':p['replacement'],
                        'agent':agent,'price':price,'members':members,'skipped_members':skipped})
    return out
