"""Read all six native coach proficiencies, including Overload."""
from pathlib import Path
import copy,json,zipfile

REVISION='native-six-coach-tactics-v1'

def read_rows(raw):
    from native_coaches import TACTICS
    if len(raw)%176:raise ValueError('教练表长度改变，未读取战术熟练度')
    result={}
    for at in range(0,len(raw),176):
        value=int.from_bytes(raw[at:at+176],'little');cid=str(value&((1<<64)-1))
        if cid in result:raise ValueError('教练表存在重复编号')
        result[cid]={key:(value>>bit)&127 for key,bit in TACTICS.items()}
    return result

def repair_catalogue(document,resources,fallback_resources=None):
    if document.get('coach_tactics_revision')==REVISION:return document
    result=copy.deepcopy(document);native={}
    try:
        info=json.loads((Path(resources)/'import-report.json').read_text(encoding='utf8'));source=info.get('apk')
        if source:
            from native_cpk import Cpk,unwrap
            from native_coaches import COACH
            with zipfile.ZipFile(source) as archive:
                for folder in ('livedata','custom-resources/legends-v10'):
                    name='assets/gateway-release/'+folder+'/dt870_mobile_and.cpk'
                    if name in archive.namelist():
                        cpk=Cpk(archive.read(name))
                        if COACH in cpk.files:native.update(read_rows(unwrap(cpk.read(COACH))))
    except (OSError,ValueError,KeyError,zipfile.BadZipFile):pass
    fallback={}
    if not native and fallback_resources:
        try:
            current=json.loads((Path(resources)/'native-resource-profile.json').read_text(encoding='utf8'))
            original=json.loads((Path(fallback_resources)/'native-resource-profile.json').read_text(encoding='utf8'))
            if all(current.get(k) and current[k]==original.get(k) for k in ('release_id','native_engine_sha256')):
                bundled=json.loads((Path(fallback_resources)/'coaches.json').read_text(encoding='utf8'))
                if bundled.get('coach_tactics_revision')==REVISION:fallback={str(c['id']):c['tactics']['overload'] for c in bundled['coaches']}
        except (OSError,ValueError,KeyError):pass
    for row in result.get('coaches',[]):
        tactics=row.setdefault('tactics',{})
        if str(row['id']) in native:tactics.update(native[str(row['id'])])
        else:tactics.setdefault('overload',fallback.get(str(row['id']),int((row.get('raw_payload') or {}).get('overload') or 0)))
        row.setdefault('raw_payload',{}).update(tactics)
    result['coach_tactics_revision']=REVISION
    return result
