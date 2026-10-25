"""Stable, locally verified skill names independent of APK editor labels."""
import json
from pathlib import Path
from studio_resources import bundled_resources


def apply_labels(catalog, resources=None):
    resources=Path(resources) if resources else bundled_resources()
    path=resources/'skill-labels-zh.json'
    if not path.is_file():return
    data=json.loads(path.read_text(encoding='utf8'))
    parameters={str(k):v for k,v in catalog['PARAMETER_BY_SKILL'].items()}
    labels={str(k):v for k,v in catalog['SKILL_LABELS'].items()}
    aliases={str(k):list(v) for k,v in catalog.get('SKILL_ALIASES',{}).items()}
    for row in data['rows']:
        key=str(row['id'])
        if int(parameters.get(key,-1))!=row['parameter']:
            raise ValueError('已核对的技能名称与原生参数不一致：'+key)
        # Unreleased native slots are not gameplay implementations. Keep the
        # reserved markers until their actual effects have been implemented.
        if row['reserved']:continue
        previous=labels.get(key,'');label=row['label'].replace('撓','挠')
        labels[key]=label
        aliases[key]=sorted({v for v in (*aliases.get(key,[]),previous,row.get('previous',''),row['english']) if v and v!=label})
    from native_skill_effects import VISIBLE,DESCRIPTIONS
    for skill,label in VISIBLE.items():
        key=str(skill);aliases[key]=sorted(set(aliases.get(key,[])+[labels.get(key,'')])-{''})
        labels[key]=label
    catalog.update(SKILL_LABELS=labels,SKILL_ALIASES=aliases,SKILL_DESCRIPTIONS={str(k):v for k,v in DESCRIPTIONS.items()})
