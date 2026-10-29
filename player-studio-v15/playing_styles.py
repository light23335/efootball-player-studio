"""Complete native playing-style options, independent of the APK editor's list.

V17's editor table omits Target Man (22) and High Line GK (35), although both
are present in the native name/phase tables. Apply this to existing and newly
imported catalogues so a database refresh cannot reintroduce the omissions.
"""
import json
from studio_resources import bundled_resources


def definitions():
    return json.loads((bundled_resources()/'native-playing-styles.json').read_text(encoding='utf8'))['rows']


def apply_catalogue(catalogue):
    original=catalogue.get('PLAY_STYLES',{})
    if not isinstance(original,dict):raise ValueError('比赛风格目录格式不正确')
    options={}
    for phase in ('attack','defense'):
        values=original.get(phase,{})
        if not isinstance(values,dict):raise ValueError('比赛风格分组格式不正确')
        options[phase]={str(k):v for k,v in values.items()}
        options[phase].setdefault('0','无风格')
    for row in definitions():
        key=str(row['id']);phase=row['phase'];other='defense' if phase=='attack' else 'attack'
        # Keep upstream names/aliases while repairing known native phases.
        label=options[phase].get(key) or options[other].get(key) or row['label']
        options[phase][key]=label
        options[other].pop(key,None)
    catalogue['PLAY_STYLES']={phase:dict(sorted(values.items(),key=lambda item:(not item[0].isdigit(),int(item[0]) if item[0].isdigit() else item[0]))) for phase,values in options.items()}
    return catalogue
