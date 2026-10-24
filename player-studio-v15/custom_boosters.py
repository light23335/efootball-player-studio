"""Capabilities verified against V15's 26 native booster accessors."""
MIN_EFFECT=0
MAX_EFFECT=20
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
