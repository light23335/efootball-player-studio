"""Catalogue every separable native front-card design in the supplied APKs."""
from pathlib import Path
import collections, hashlib, json, re, sqlite3

ROOT=Path(__file__).resolve().parent
SLOTS=('f01','f02','f03','f04','f05','f07','f10')
ORDER={'f01':0,'f02':1,'f04':3,'f03':4,'f05':5,'f07':7,'f10':8}
STYLE_KIND={'0000':'Standard','0100':'Legendary','0101':'Legendary','0200':'BigTime','0201':'BigTime',
            '0300':'Trending','0301':'Trending','0302':'Trending','0303':'Trending',
            '0400':'Featured','0401':'Featured','0500':'Epic','0501':'BigTime','0600':'Highlight','0601':'Highlight'}

def original_date(label):
    from datetime import datetime
    match=re.search(r"(\d{1,2}) ([A-Za-z]{3}) '(\d{2})",label)
    if not match:return ''
    months='Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()
    try:
        month=months.index(match[2])+1;year=int(match[3]);year+=1900 if year>50 else 2000
        return datetime(year,month,int(match[1])).date().isoformat()
    except ValueError:return ''

def build(resources=None,write=True,verbose=True):
    resources=Path(resources) if resources is not None else ROOT/'resources'
    db=sqlite3.connect(resources/'library.sqlite3');db.row_factory=sqlite3.Row
    assets={}
    for row in db.execute('SELECT * FROM assets WHERE kind IN ("card","portrait") ORDER BY CASE WHEN path LIKE "PesMobile/%" THEN 0 ELSE 1 END'):
        assets.setdefault(row['name'],dict(row))
    aliases=dict(db.execute('SELECT before,after FROM card_aliases'))
    movies={Path(p).stem:p for p in json.loads((resources/'native-card-media.json').read_text(encoding='utf8'))['movies']}
    def alias(name):
        seen=set()
        while name in aliases and name not in seen:seen.add(name);name=aliases[name]
        return name
    def resolve(style,agent,limited,pid=None,portrait_pid=None,league=0):
        layers=[]
        for slot in SLOTS:
            common=([f'{style}_{agent}_{slot}_lim',f'{style}_{slot}_lim'] if limited else [])+[f'{style}_{agent}_{slot}',f'{style}_{slot}']
            # Per-card f01 textures can already contain a full photographed
            # player (POTW is one example). Only shared design components are
            # safe blank presets; never present a baked photo as a clean frame.
            names=common
            if style=='0000' and slot=='f01':names += [f'0000_f01_{league}_','0000_f01_0_']
            row=next((assets[alias(n)] for n in names if alias(n) in assets),None)
            if row and not (re.fullmatch(r'\d{4}(?:_\d{1,4})?_f\d\d(?:_lim)?',row['name']) or
                            style=='0000' and re.fullmatch(r'0000_f01_\d{1,6}_',row['name'])):
                row=None  # A shared alias can still terminate at a baked card photo.
            video=next((movies[m] for n in common for m in [n+'_v',alias(n+'_v'),alias(n)+'_v'] if m in movies),None) if slot in ('f02','f03','f05','f10') else None
            if video:layers.append({'slot':slot,'kind':'video','path':video,'name':Path(video).stem})
            elif row:layers.append({k:row[k] for k in ('id','path','name')}|{'slot':slot,'kind':'image'})
        for row in layers:row['blend']='screen' if row['slot'] in ('f03','f05','f07','f10') else 'source-over'
        return sorted(layers,key=lambda r:ORDER[r['slot']])
    presets={};families={};provenance=collections.Counter()
    def add(kind,style,agent,limited,layers,source_id,label,name):
        if not layers or not any(r['slot'] in ('f01','f02','f10') for r in layers):return
        kind=STYLE_KIND.get(style,kind)
        signature=json.dumps([kind,[(r['slot'],r['path'],r['blend']) for r in layers]],separators=(',',':'))
        key=hashlib.sha256(signature.encode()).hexdigest()[:24]
        if key not in presets:
            title=re.sub(r"\b\d{1,2} [A-Za-z]{3} '\d{2}\b",'',label).strip()
            for prefix in ('Big Time','Epic'):
                if title.startswith(prefix):title=title[len(prefix):].strip()
            presets[key]={'id':key,'card_type':kind,'native_style':style,'native_agent':agent,'limited':limited,
                          'title':title or ('限定版' if limited else '原版设计'), 'design_code':f'{style} / {agent}'+(' · 限定' if limited else ''),
                          'source_id':str(source_id or '7511'),'sample_date':original_date(label),'layers':layers,
                          'examples':[],'labels':[],'source_count':0}
        item=presets[key];item['source_count']+=1
        if name and name not in item['examples'] and len(item['examples'])<8:item['examples'].append(name)
        if label and label not in item['labels'] and len(item['labels'])<8:item['labels'].append(label)
        provenance[kind]+=1
    for row in db.execute('SELECT id,name_en,card_type,payload FROM players'):
        pid=row['id'];n=int(pid);style_byte=(n>>40)&255;style=f'{style_byte>>4:02d}{style_byte&15:02d}';agent=(n>>28)&4095;limited=bool(n&(1<<48))
        if style not in STYLE_KIND:continue
        payload=json.loads(row['payload']);physical=alias(pid+'_l').split('_')[0]
        key=(style,agent,limited);families.setdefault(key,pid)
        layers=resolve(style,agent,limited,pid,physical,payload.get('_league_id',0))
        add(row['card_type'],style,agent,limited,layers,pid,payload.get('_studio_card_label',''),row['name_en'])
    # Include original designs present in the resource packages even when the
    # player database contains no current card using that design.
    for name in list(assets)+list(movies):
        match=re.fullmatch(r'(\d{4})(?:_(\d+))?_f\d\d(_lim)?(?:_v)?',name)
        if not match or match[1] not in STYLE_KIND:continue
        style,agent,limited=match[1],int(match[2] or 0),bool(match[3])
        layers=resolve(style,agent,limited)
        anchor=families.get((style,agent,limited)) or next((pid for (s,a,l),pid in families.items() if s==style),'7511')
        add(STYLE_KIND[style],style,agent,limited,layers,anchor,'','')
    rows=list(presets.values())
    result={'version':1,'source':'provided APK front-card layers only; portrait, player signature and date texture excluded',
            'excluded_slots':['portrait','f06','f09','bXX','mXX'],'counts':dict(collections.Counter(r['card_type'] for r in rows)),
            'rows':rows}
    db.close()
    dest=resources/'native-card-presets.json'
    if write:dest.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    if verbose:print(json.dumps({'total':len(rows),'counts':result['counts']}))
    return result

if __name__=='__main__':build()
