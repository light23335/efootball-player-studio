"""Keep platform-specific models out of cross-game project imports by default."""
import copy

PLATFORMS={'android','windows-x64'}


def platform(project,declared=None):
    value=declared or project.get('game_platform')
    if value in PLATFORMS:return value
    if project.get('pc_native_template') or '-pc' in str(project.get('studio_version','')):return 'windows-x64'
    if str((project.get('model',{}).get('native_source') or {}).get('path','')).removeprefix('../../../').startswith('PesConsole/'):
        return 'windows-x64'
    return 'android'


def prepare(project,destination,declared=None):
    if destination not in PLATFORMS:raise ValueError('工程目标平台无效')
    value=copy.deepcopy(project);origin=platform(value,declared)
    if origin!=destination:
        model=value.setdefault('model',{})
        for key in ('asset','texture','rigged_asset','native_source','morphs','animation','binding_handles'):
            model.pop(key,None)
        for key,item in list((value.get('native_art') or {}).items()):
            if key in ('model','face','head','hair') or isinstance(item,dict) and str(item.get('asset_id','')).lower().endswith(('.glb','.obj')):
                value['native_art'].pop(key,None)
        value['project_import']={'source_platform':origin,'target_platform':destination,'models_skipped':True}
    value['game_platform']=destination
    return value
