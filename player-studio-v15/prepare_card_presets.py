from pathlib import Path
import sys,json,hashlib,collections
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'player-studio'))
from app import Store
from native_library import NativeLibrary
lib=NativeLibrary(root/'player-studio/resources',root/'球员工坊',Store(root/'.work/preset-art-data'))
path=root/'player-studio/resources/native-card-presets.json';catalog=json.loads(path.read_text(encoding='utf8'))
refs={r['path'] for p in catalog['rows'] for r in p['layers'] if r['kind']=='image'}
missing=[p for p in refs if not (lib.converted/Path(p).with_suffix('.png')).is_file()]
print('Images',len(refs),'uncached',len(missing),flush=True)
for i in range(0,len(missing),500):
    lib.run(missing[i:i+500]);print('Converted batch',i//500+1,flush=True)
hashes={p:hashlib.sha256((lib.converted/Path(p).with_suffix('.png')).read_bytes()).hexdigest() for p in refs if (lib.converted/Path(p).with_suffix('.png')).is_file()}
merged={};redirect={}
for row in catalog['rows']:
    key=json.dumps([row['card_type'],[(r['slot'],hashes.get(r['path'],r['path']),r['blend']) for r in row['layers']]])
    if key in merged:
        prior=merged[key];prior['source_count']+=row['source_count'];redirect[row['id']]=prior['id']
        for field in ['examples','labels']:
            prior[field]=list(dict.fromkeys(prior[field]+row[field]))[:12]
    else:merged[key]=row
catalog['rows']=list(merged.values());catalog['counts']=dict(collections.Counter(r['card_type'] for r in catalog['rows']));catalog['pixel_deduplicated']=True
catalog['physical_design_count']=len(catalog['rows'])+len(redirect)
path.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')),encoding='utf8')
(root/'.work/studio-qa/preset-pixel-audit.json').write_text(json.dumps({'input_designs':catalog['physical_design_count'],'unique_designs':len(catalog['rows']),'deduplicated':len(redirect),'counts':catalog['counts'],'images':len(refs),'missing_images':[p for p in refs if p not in hashes]},indent=2),encoding='utf8')
print('Result',len(catalog['rows']),catalog['counts'],flush=True)
