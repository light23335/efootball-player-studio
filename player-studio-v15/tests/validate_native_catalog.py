"""Compare mobile decoding against actual V13 native server entries."""
import collections
import json
from pathlib import Path
import sqlite3

root=Path(__file__).absolute().parents[2]
resources=root/'player-studio/resources'
cat=json.loads((resources/'catalog.json').read_text(encoding='utf8'))
mapping=json.loads((resources/'native-ability-bits.json').read_text(encoding='utf8'))
schema=json.loads((root/'.work/asset-tools/pes-tools/pesdb_schema.json').read_text(encoding='utf8'))['tables']['Player.bin/400']['fields']
bits={f['name']:(f['bit'],f['width']) for f in schema}
raw=(root/'.work/game-assets/db/live-player.bin').read_bytes()
c=sqlite3.connect(root/'.work/studio-qa/seed.sqlite3')
known={str(i):(json.loads(p),t) for i,p,t in c.execute('SELECT card_id,payload,card_type FROM managed_cards')}
c.close();counts=collections.Counter()
for offset in range(0,len(raw),400):
    b=raw[offset:offset+400];pid=str(int.from_bytes(b[8:16],'little'))
    if pid not in known:continue
    p,kind=known[pid];value=int.from_bytes(b,'little');params=p['parameters']
    get=lambda k:(value>>bits[k][0])&((1<<bits[k][1])-1)
    counts['server_overlap']+=1
    assert get('height_cm')+100==params[47]
    assert get('weight_kg')+30==params[48]
    assert get('age')+10==params[46]
    assert get('foot')==params[43]
    assert get('weak_foot_accuracy')==params[33]
    assert get('weak_foot_usage')==params[45]
    assert get('injury_resistance')==params[42]
    assert get('form')==params[41]
    for i,pos in enumerate(cat['APTITUDES']):assert get('aptitude.'+pos)==params[i+1]
    if kind not in ('Standard','UNKNOWN'):
        counts['special_cards_all_26_equal']+=1
        assert all(((value>>m['bit'])&63)+40==params[int(i)] for i,m in mapping.items())
        attack,defense=get('style.in_possession'),get('style.out_of_possession')
        if attack in (9,16,17):attack,defense=0,attack
        assert [attack,defense]==p['play_style']
assert counts['server_overlap']==14379
assert counts['special_cards_all_26_equal']==13615
report={'status':'passed','client_records':len(raw)//400,**counts,'abilities_checked':13615*26,'height_weight_age_foot_traits_aptitudes_exact':True,'styles_exact_on_special_cards':True,'note':'Mobile offsets are calibrated against the supplied V13 data; PC field semantics are not assumed.'}
(resources/'native-schema-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report))
