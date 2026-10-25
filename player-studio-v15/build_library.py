"""Build an exact catalogue of the supplied V13 player table and native assets.

Development input files are decoded from the user's APKs. No network is used.
Field layout reference: tools/data/pesdb_schema.json in eFootball-Master-League.
"""
from pathlib import Path
import csv
import gzip
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from card_types import editor_card_type

ROOT=Path(__file__).absolute().parent
WORK=ROOT.parent/'.work/game-assets'
CAT=json.loads((ROOT/'resources/catalog.json').read_text(encoding='utf8'))

def main():
    path=ROOT/'resources/library.sqlite3'
    if path.exists():path.unlink()
    c=sqlite3.connect(path)
    c.executescript('''CREATE TABLE players(id TEXT PRIMARY KEY,name TEXT,name_en TEXT,search TEXT,position TEXT,card_type TEXT,overall INTEGER,level_limit INTEGER,base_id TEXT,payload TEXT,source TEXT);
      CREATE TABLE assets(id TEXT PRIMARY KEY,path TEXT UNIQUE,name TEXT,kind TEXT,player_key TEXT);
      CREATE INDEX player_search ON players(name_en); CREATE INDEX asset_kind ON assets(kind,player_key);
      CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);''')
    with zipfile.ZipFile(ROOT.parent/'73efootball-V13.apk') as z:
        names=json.loads(gzip.decompress(z.read('assets/gateway-release/outputs/reference/player_editor_names.json.gz')))
        classes={r['player_id']:r['card_class'] for r in csv.DictReader(io.StringIO(z.read('assets/gateway-release/outputs/reference/card-class-table.csv').decode()))}
    schema=json.loads((ROOT.parent/'.work/asset-tools/pes-tools/pesdb_schema.json').read_text(encoding='utf8'))['tables']['Player.bin/400']['fields']
    bits={f['name']:(f['bit'],f['width']) for f in schema}
    mobile_abilities=json.loads((ROOT/'resources/native-ability-bits.json').read_text(encoding='utf8'))
    mobile_skills=json.loads((ROOT/'resources/native-skill-bits.json').read_text(encoding='utf8'))
    raw=(WORK/'db/live-player.bin').read_bytes()
    assert len(raw)%400==0
    records={}
    variation={}
    detail=(WORK/'db/PlayerVariationDetail.bin').read_bytes()
    assert len(detail)%168==0
    for offset in range(0,len(detail),168):
        pid=str(int.from_bytes(detail[offset:offset+8],'little'));label=detail[offset+12:offset+140].split(b'\0',1)[0].decode('utf8','replace')
        variation[pid]=label
    for offset in range(0,len(raw),400):
        b=raw[offset:offset+400];value=int.from_bytes(b,'little')
        get=lambda k: (value>>bits[k][0])&((1<<bits[k][1])-1)
        pid=str(int.from_bytes(b[8:16],'little'))
        strings=[b[88+i*61:149+i*61].split(b'\0',1)[0].decode('utf8','replace').strip() for i in range(5)]
        en=strings[4] or strings[3] or strings[1] or strings[0] or pid
        label=names.get(pid,[en,en])
        p=[0]*147;p[0]=get('position')
        if p[0]>=len(CAT['POSITIONS']):raise ValueError('Unknown native position: '+pid)
        for i,mapping in mobile_abilities.items():p[int(i)]=((value>>mapping['bit'])&63)+40
        for pos in CAT['POSITIONS']:
            # The server parameter aptitude ordering differs from position ordering.
            aptitude_order=CAT['APTITUDES']
            p[aptitude_order.index(pos)+1]=get('aptitude.'+pos)
        p[33]=get('weak_foot_accuracy');p[41]=get('form');p[42]=get('injury_resistance');p[43]=get('foot');p[45]=get('weak_foot_usage');p[46]=get('age')+10;p[47]=get('height_cm')+100;p[48]=get('weight_kg')+30
        from native_skill_effects import decode_skills
        skill_ids=decode_skills(value,p,CAT,mobile_skills)
        attack,defense=get('style.in_possession'),get('style.out_of_possession')
        if attack in (9,16,17):defense,attack=attack,0
        p[61]=attack or defense
        payload={'gameplayer_id':{'id':int(pid),'serial':0},'parameters':p,'level_info':{'level':1,'level_limit':None},'play_style':[attack,defense],'initial_base_team_id':get('club'),'_nation_id':get('nationality'),'_studio_skill_ids':skill_ids,'_studio_names':strings,'_studio_unknown_level_limit':True,'_studio_client_record':b.hex(),'_studio_partial_skill_mapping':True}
        kind=classes.get(pid,'UNKNOWN');variant=variation.get(pid,'');payload['_studio_card_label']=variant
        if ' Custom ' in variant:
            prefix,title=variant.split(' Custom ',1);label=[title,title];kind='BigTime' if prefix=='Big Time' else prefix
        records[pid]=[label[0] or en,label[1] or en,payload,kind,'客户端 Player.bin / 400']
    seed=sqlite3.connect(WORK.parent/'studio-qa/seed.sqlite3')
    for pid,raw_payload,kind in seed.execute('SELECT card_id,payload,card_type FROM managed_cards'):
        payload=json.loads(raw_payload);prior=records.get(pid);label=names.get(pid)
        en=(label[1] if label else (prior[1] if prior else payload.get('name_en') or payload.get('name') or pid))
        name=(label[0] if label else (prior[0] if prior else en))
        if prior:
            payload={**{k:v for k,v in prior[2].items() if k in ('_studio_client_record','_studio_names','_studio_card_label')},**payload}
        payload['_studio_card_label']=variation.get(pid,payload.get('_studio_card_label',''))
        records[pid]=[name,en,payload,kind,'V13 本地卡池 managed_cards']
    seed.close()
    base_names={}
    for pid,(name,en,p,kind,source) in records.items():
        from native_celebration import restore_payload
        restore_payload(p)
        if int(pid)<2**24:base_names.setdefault(en.casefold(),[]).append(pid)
    for pid,(name,en,p,kind,source) in records.items():
        p['_studio_native_card_class']='Epic' if kind=='BigTime' else kind
        kind=editor_card_type(kind,p.get('_studio_card_label',''))
        parameters=p['parameters'];level=p.get('level_info',{}).get('level_limit')
        # Names are an exact catalogue join, never a low-bit mask guess.
        candidates=base_names.get(en.casefold(),[])
        base_id=candidates[0] if len(candidates)==1 else pid
        aliases={'Thierry Henry':'亨利 蒂埃里·亨利','Zidane':'齐达内 齐丹 Zinedine Zidane','Ronaldo Nazario':'罗纳尔多 大罗 R9'}
        search=' '.join([pid,name,en,aliases.get(en,''),*p.get('_studio_names',[])]).casefold()
        c.execute('INSERT INTO players VALUES(?,?,?,?,?,?,?,?,?,?,?)',(pid,name,en,search,CAT['POSITIONS'][parameters[0]],kind,p.get('_overall'),level,base_id,json.dumps(p,ensure_ascii=False,separators=(',',':')),source))
    lines=(WORK/'all-list.txt').read_text(encoding='utf8').splitlines()
    for asset in sorted(set(lines)):
        if not asset.endswith('.uasset'):continue
        name=asset.rsplit('/',1)[-1][:-7]
        if '/Thumbnail/Player/' in asset or ('/RealFace/' in asset and re.fullmatch(r'\d+(?:_|f)',name)):
            kind='portrait' if re.fullmatch(r'\d+_(?:l)?',name) else 'card'
            match=re.match(r'(\d+)',name) if kind=='portrait' or re.fullmatch(r'\d+f',name) else re.search(r'(\d{6,})',name)
            key=match.group(1) if match else ''
        elif '/character/' in asset.casefold() and name.startswith('SK_'):
            kind='model';match=re.match(r'SK_(\d+)',name);key=match.group(1) if match else ''
        else:continue
        identifier=hashlib.sha256(asset.encode()).hexdigest()[:24]
        c.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?)',(identifier,asset,name,kind,key))
    stats={'players':len(records),'client_player_records':len(raw)//400,'assets':c.execute('SELECT count(*) FROM assets').fetchone()[0],'by_asset_kind':dict(c.execute('SELECT kind,count(*) FROM assets GROUP BY kind')),'source':'73efootball-V13.apk + 73efootball-离线资源包-V9+.apk','schema':'Player.bin/400; height+100, weight+30, abilities+40','field_reference':'https://github.com/tjgg260/eFootball-Master-League/blob/main/tools/data/pesdb_schema.json'}
    c.execute('INSERT INTO meta VALUES(?,?)',('summary',json.dumps(stats,ensure_ascii=False)))
    c.commit();c.execute('VACUUM');c.close()
    print(json.dumps(stats,ensure_ascii=True))

if __name__=='__main__':main()
