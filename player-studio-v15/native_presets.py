"""Native backgrounds/frames for personal portraits; no source player images."""
from pathlib import Path
import json
from native_movie import convert_movie


class NativePresets:
    def __init__(self,library):
        self.library=library
        self.catalog=json.loads((library.resources/'native-card-presets.json').read_text(encoding='utf8'))
        self.rows={row['id']:row for row in self.catalog['rows']}

    def search(self,body):
        kind=body.get('kind','BigTime');query=str(body.get('query','')).strip().casefold()[:120]
        rows=[r for r in self.rows.values() if (not kind or r['card_type']==kind) and
              (not query or query in ' '.join([r['title'],r['design_code'],*r['labels'],*r['examples']]).casefold())]
        rows.sort(key=lambda r:(r['card_type']!='BigTime',r['card_type']!='Epic',r.get('available') is False,bool(r.get('flat_base_color')),r['native_agent']>=4000,-r['native_agent'],r['limited'],r['title']))
        page=max(0,int(body.get('page',0)));limit=12;pages=max(1,(len(rows)+limit-1)//limit);page=min(page,pages-1)
        return {'rows':[{k:v for k,v in r.items() if k!='layers'}|{'animated':any(l['kind']=='video' for l in r['layers'])}
                        for r in rows[page*limit:(page+1)*limit]],'total':len(rows),'page':page,'pages':pages,
                'counts':self.catalog['counts'],'all_count':len(self.rows),'usable_total':sum(r.get('available') is not False for r in rows)}

    def get(self,identifier):
        if identifier not in self.rows:raise ValueError('卡面预设不在当前原版资源库中')
        return self.rows[identifier]

    def previews(self,identifiers):
        if not isinstance(identifiers,list) or not 1<=len(identifiers)<=12:raise ValueError('每次读取 1–12 个原版预设')
        rows=[self.get(i) for i in dict.fromkeys(identifiers)];lib=self.library
        if lib.state['phase']!='ready':raise ValueError('请先准备原版资源缓存')
        images=list(dict.fromkeys(r['id'] for row in rows for r in row['layers'] if r['kind']=='image'))
        converted={}
        for start in range(0,len(images),24):converted.update(lib.convert({'ids':images[start:start+24]})['results'])
        movies={r['path']:r for row in rows for r in row['layers'] if r['kind']=='video'}
        video_results={}
        with lib.convert_lock:
            needed=[p for p in movies if not (lib.converted/p).is_file()]
            if needed:lib.run(needed,'raw')
            for ref in movies:
                source=lib.converted/ref
                try:
                    dest=source.with_suffix('.webm');meta=convert_movie(source,dest,lib.ffmpeg)
                    asset=lib.store.import_asset(dest,'video');video_results[ref]={'asset_id':asset['id'],'url':asset['url'],**meta}
                except (ValueError,OSError) as exc:video_results[ref]={'error':str(exc)}
        result={}
        for row in rows:
            layers=[];missing=[]
            for layer in row['layers']:
                imported=converted.get(layer.get('id'),{}) if layer['kind']=='image' else video_results[layer['path']]
                if imported.get('asset_id'):layers.append({**layer,**imported,'kind':layer['kind']})
                else:missing.append({'path':layer['path'],'reason':imported.get('error','原版图层未读取')})
            result[row['id']]={'source_id':row['source_id'],'preset_id':row['id'],'card_type':row['card_type'],
                               'source_label':row['title'],'native_style':row['native_style'],'native_agent':row['native_agent'],
                               'layers':layers,'fonts':{},'layout':lib.card_media['layout'],'missing':missing,'preview_only':True}
        return {'results':result}

    def apply(self,body):
        row=self.get(body['id']);lib=self.library
        if row.get('available') is False:raise ValueError(row['unavailable_reason'])
        card=self.previews([row['id']])['results'][row['id']]
        if card['missing']:raise ValueError('此预设有原版图层尚未读取，未替换当前卡面')
        refs={name:'PesMobile/Content/Platforms/_Android/Assets/ui/Font/'+font+'.ufont'
              for name,font in [('sans','eFootballSans-Regular'),('headline','eFootballStencil-Regular'),('chinese','NotoSansSC-SemiBold')]}
        with lib.convert_lock:
            needed=[p for p in refs.values() if not (lib.converted/p).is_file()]
            if needed:lib.run(needed,'raw')
            for name,ref in refs.items():
                source=lib.converted/ref;raw=source.read_bytes();font=source.with_suffix('.otf' if raw[:4]==b'OTTO' else '.ttf');font.write_bytes(raw)
                asset=lib.store.import_asset(font,'font');card['fonts'][name]={'asset_id':asset['id'],'path':ref}
        card['info']=lib.card_info(row['source_id'],body.get('team_id',0),body.get('nation_id',0))
        card['info']['rarity']=max(1,min(5,int(body.get('rarity',5))))
        card.update(version=1,composition_revision=3,preview_only=False,
                    ui={k:lib.card_widgets[k] for k in ('widgets','states','native_dispatch')},
                    preset={'id':row['id'],'title':row['title'],'design_code':row['design_code'],'sample_date':row['sample_date'],'limited':row['limited'],
                            'portrait_removed':True,'date_texture_removed':True,'signature_removed':True},
                    video_frames_unchanged=True,renderer='native-assets-browser-composite',material_verified_in_game=False)
        return card
