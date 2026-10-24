from pathlib import Path
import json,collections
from PIL import Image
root=Path(__file__).resolve().parents[1];path=root/'player-studio/resources/native-card-presets.json';catalog=json.loads(path.read_text(encoding='utf8'))
refs={l['path'] for r in catalog['rows'] for l in r['layers'] if l['kind']=='image'}
flat={}
for ref in refs:
    image=Image.open(root/'球员工坊/library/converted'/Path(ref).with_suffix('.png')).convert('RGBA')
    extrema=image.getextrema()
    if all(lo==hi for lo,hi in extrema):flat[ref]=[v[0] for v in extrema]
print('flat',len(flat))
for ref,color in flat.items():print(Path(ref).stem,color)
rows=catalog['rows']
for r in rows:
    base=next((flat.get(l['path']) for l in r['layers'] if l['slot']=='f01' and l['path'] in flat),None)
    if base and base[3]>0 and max(base[:3])-min(base[:3])>20:r['flat_base_color']='#'+''.join(f'{c:02x}' for c in base[:3])
path.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')),encoding='utf8')
(root/'.work/studio-qa/preset-solid-colour-audit.json').write_text(json.dumps({'flat_images':flat,'counts':catalog['counts']},indent=2),encoding='utf8')
print('remaining',len(rows),catalog['counts'])
