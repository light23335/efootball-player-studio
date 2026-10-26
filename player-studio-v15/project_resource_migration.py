"""Resolve stale cross-game references using the player's explicit native ID.

Work on copies: personal geometry, authored card layers and save identities
remain untouched. A valid chosen appearance donor always takes precedence.
"""
import copy,sqlite3,contextlib
from native_appearance import profile


def prepare(project,resources,assets=None):
    p=copy.deepcopy(project);model=p.get('model',{});identity=p.get('identity',{});changes=[]
    bound=identity.get('original_player_id')
    selected=str(bound) if bound and identity.get('bind_original_player') else None
    with contextlib.closing(sqlite3.connect(resources/'library.sqlite3')) as db:
        valid=bool(selected and db.execute('select 1 from players where id=?',(selected,)).fetchone())
        if valid:
            old=model.get('appearance_source_id')
            if old is not None and profile(resources,old) is None:
                if profile(resources,selected) is None:raise ValueError('绑定球员在当前库中没有原版体型记录，请重新选择体型来源')
                model['appearance_source_id']=selected;changes.append({'kind':'appearance','old':str(old),'new':selected})
            card=p.get('native_card') or {}
            old=card.get('source_id')
            if old and not db.execute('select 1 from players where id=?',(str(old),)).fetchone():
                card['source_id']=selected;changes.append({'kind':'card-donor','old':str(old),'new':selected})
    native=(model.get('native_source') or {}).get('path')
    if native and assets is not None:
        path=native
        if path.startswith('/Game/'):path='../../../PesMobile/Content/'+path[6:]+'.uasset'
        elif not path.startswith('../../../'):path='../../../'+path
        if path not in assets.files:
            if not model.get('asset'):raise ValueError('旧版脸模在当前游戏不存在，工程也没有内嵌 GLB；请重新导入脸模')
            model['native_source']=None
            changes.append({'kind':'embedded-glb','old':native,'new':model['asset']})
    return p,changes
