"""Coach country is native data; the owned payload supplies its selected club."""
from pathlib import Path
import copy,json,sqlite3,zipfile

REVISION='native-coach-country-owned-club-v1'
NATION_BIT=170
NATION_WIDTH=9
MAX_TEAM_ID=131071


def normalize(value):
    raw=value.get('raw_payload') or {}
    if not isinstance(raw,dict):raw={}
    def number(key,maximum,fallback=0):
        result=value.get(key,fallback)
        if result is None:result=0
        if type(result) is not int or not 0<=result<=maximum:raise ValueError('教练'+('国籍' if key=='nation_id' else '俱乐部')+'编号无效')
        return result
    source=value.get('native_source_id')
    if source is not None:
        source=str(source)
        if not source.isascii() or not source.isdecimal() or not 0<int(source)<2**63:raise ValueError('原版教练来源编号无效')
    return {'nation_id':number('nation_id',511,raw.get('_nation_id',0)),
            'team_id':number('team_id',MAX_TEAM_ID,value.get('initial_base_team_id',raw.get('initial_base_team_id',0))),
            'native_source_id':source}


def owned_payloads(archive):
    result={};path='assets/gateway-release/outputs/efootball/local-club.sqlite3'
    if path in archive.namelist():
        db=sqlite3.connect(':memory:')
        try:
            db.deserialize(archive.read(path))
            for cid,raw in db.execute('SELECT coach_id,json FROM coaches'):result[str(cid)]=json.loads(raw)
        finally:db.close()
    from personal_source import PATH
    if PATH in archive.namelist():
        for row in json.loads(archive.read(PATH)).get('coaches',[]):result[str(row['id'])]=copy.deepcopy(row['payload'])
    return result


def country(row):
    if len(row)!=176:raise ValueError('原生教练记录长度改变')
    return (int.from_bytes(row,'little')>>NATION_BIT)&511


def apply(row,native,payloads):
    cid=str(row['id']);owned=payloads.get(cid);row.update(nation_id=country(native),team_id=int(owned.get('initial_base_team_id') or 0) if owned else 0,
        native_source_id=cid,team_source='owned-payload' if owned else 'unavailable',identity_available=True)
    row.update(normalize(row))
    return row


def repair_catalogue(document,resources):
    """Repair old read-only imported options in memory, without touching saves."""
    if document.get('coach_identity_revision')==REVISION:return document
    result=copy.deepcopy(document);native={};payloads={}
    report=Path(resources)/'import-report.json'
    try:
        apk=json.loads(report.read_text(encoding='utf8'))['apk']
        from native_cpk import Cpk,unwrap
        from native_coaches import COACH
        with zipfile.ZipFile(apk) as z:
            payloads=owned_payloads(z)
            for name in ('livedata','custom-resources/legends-v10'):
                path='assets/gateway-release/'+name+'/dt870_mobile_and.cpk'
                if path not in z.namelist():continue
                table=Cpk(z.read(path))
                if COACH not in table.files:continue
                raw=unwrap(table.read(COACH))
                if len(raw)%176:raise ValueError('原生教练表长度改变')
                for at in range(0,len(raw),176):native[str(int.from_bytes(raw[at:at+8],'little'))]=raw[at:at+176]
    except (OSError,ValueError,KeyError,sqlite3.DatabaseError,zipfile.BadZipFile):pass
    for row in result.get('coaches',[]):
        if str(row['id']) in native:apply(row,native[str(row['id'])],payloads)
        else:
            available='nation_id' in row
            row.update(normalize({'nation_id':row.get('nation_id',0),'team_id':row.get('team_id',0),'native_source_id':str(row['id'])}))
            row['identity_available']=available
            row.setdefault('team_source','unavailable')
    if native:result['coach_identity_revision']=REVISION
    return result
