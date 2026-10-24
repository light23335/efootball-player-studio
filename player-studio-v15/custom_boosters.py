"""Capabilities verified against V15's 26 native booster accessors."""
MIN_EFFECT=0
MAX_EFFECT=20
CUSTOM_MIN=1
CUSTOM_MAX=1023
CUSTOM_IDS=tuple(range(1000,1024))+tuple(range(999,0,-1))

def text_key(bid):
    if type(bid) is not int or not CUSTOM_MIN<=bid<=CUSTOM_MAX:
        raise ValueError('自建增能原生编号超出 1–1023 范围')
    return 60000+(bid-1000)*2 if bid>=1000 else 60048+(999-bid)*2

def reserve_booster(uid,registry,occupied=(),prior=None,first_slot=False,prior_alias=None):
    # Retain historical second-slot IDs. A first-slot alias must fit 8 bits.
    if first_slot and registry.get(uid,prior or 0)>255:
        if uid not in registry:registry[uid]=prior
        uid=uid+':slot0';prior=prior_alias
    if uid in registry:
        value=registry[uid];text_key(value)
        if first_slot and value>255:raise ValueError('第一槽兼容编号超过 8 位范围')
        return value
    if prior is not None:
        text_key(prior)
        if first_slot and prior>255:raise ValueError('第一槽兼容编号超过 8 位范围')
        if prior in registry.values():raise ValueError('导入的永久增能编号已被另一项增能占用，请使用配套注册表')
        registry[uid]=prior;return prior
    used=set(occupied)|set(registry.values())
    free=next((v for v in CUSTOM_IDS if v not in used and (not first_slot or v<=255)),None)
    if free is None:raise ValueError(('第一槽 8 位兼容编号' if first_slot else '游戏 10 位增能编号')+'已无空位；请减少本次使用的不同增能，共享库仍可保存 10000 项定义，旧编号不自动回收')
    registry[uid]=free;return free
BOOSTER_BITS={'14':144,'15':261,'16':192,'17':239,'18':276,'19':271,'20':244,'21':122,
              '22':229,'23':281,'24':234,'25':170,'26':266,'27':154,'28':185,
              '29':165,'30':197,'31':256,'32':224,'34':180,'35':175,'36':149,'37':249,
              '38':217,'39':160,'40':202}


def context(project,booster):
    player=project.get('display_name') or project.get('identity',{}).get('name') or '未命名球员'
    return f'{player} · 增能“{booster.get("label") or "未命名增能"}”（ID {booster.get("id","?")}）'


def canonical(booster):
    return {'uuid':booster.get('uuid'),'label':booster.get('label'),
            'conditional':bool(booster.get('conditional')),
            'effects':{str(k):v for k,v in booster.get('effects',{}).items() if v}}


def issues(project,abilities=None):
    labels=abilities or {};errors=[];selected=set(project.get('booster_ids',[]))
    for booster in project.get('custom_boosters',[]):
        if booster['id'] not in selected:continue
        effects=booster.get('effects',{});problems=[]
        unknown=[str(k) for k,v in effects.items() if v and str(k) not in BOOSTER_BITS]
        if unknown:problems.append('包含未知能力编号：'+','.join(unknown))
        invalid=[f'{labels.get(str(k),str(k))}={v}' for k,v in effects.items()
                 if type(v) is not int or not MIN_EFFECT<=v<=MAX_EFFECT]
        if invalid:problems.append('能力加成支持 0 至 +20，不支持负值：'+'、'.join(invalid))
        if booster.get('conditional'):problems.append('自定义条件触发尚未适配；请在增能编辑中明确改为常驻，或取消选用此增能')
        if problems:errors.append(context(project,booster)+'：'+'；'.join(problems))
    return errors


def validate_projects(projects,abilities=None):
    errors=[];seen={}
    for project in projects:
        errors.extend(issues(project,abilities));selected=set(project.get('booster_ids',[]))
        for b in project.get('custom_boosters',[]):
            if b['id'] not in selected:continue
            uid=b.get('uuid')
            if uid:
                value=canonical(b)
                if uid in seen and seen[uid][0]!=value:
                    errors.append(context(project,b)+'：同一永久增能在 '+seen[uid][1]+' 中的名称或效果不同；请统一定义，或新建独立增能')
                else:seen[uid]=(value,context(project,b))
    if errors:raise ValueError('\n'.join(dict.fromkeys(errors)))
