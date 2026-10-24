"""Separate native MobileIcon layers; reuse the selected card's original movies."""
from pathlib import PurePosixPath
import contextlib,re

REVISION='linked-mini-background-v4'


def plan(project,library):
    card=project.get('native_card') or {};enabled=project['appearance'].get('thumbnail_animation',True)
    paths=set(getattr(library,'card_media',{}).get('movies',[]));layers=[]
    if enabled:
        style=card.get('native_style','');agent=card.get('native_agent',0)
        if re.fullmatch(r'\d{4}',style) and type(agent) is int and 0<=agent<=4095:
            source=str(card.get('source_id',''))
            limited=(card.get('preset') or {}).get('limited',bool(int(source)&(1<<48)) if source.isdigit() else False)
            candidates=([f'{style}_{agent}_m06_lim',f'{style}_m06_lim'] if limited else [])+[f'{style}_{agent}_m06',f'{style}_m06']
            movies={PurePosixPath(p).stem:p for p in paths}
            with contextlib.closing(library.db()) as db:
                # Prefer the stock mini family. BT and many Epic presets only
                # supply F02, whose ManaTexture also lives in Variation2022.
                backgrounds=([f'{style}_{agent}_m02_lim',f'{style}_m02_lim'] if limited else [])+[f'{style}_{agent}_m02',f'{style}_m02']
                background=next((movies[n] for stem in backgrounds for n in (stem+'_v',library._alias(db,stem+'_v'),library._alias(db,stem)+'_v') if n in movies),None)
                if background:layers.append({'role':'background','path':background,'blend':'source-over','source':'native-mini'})
                effect=next((movies[n] for stem in candidates for n in (stem+'_v',library._alias(db,stem+'_v'),library._alias(db,stem)+'_v') if n in movies),None)
            if effect:layers.append({'role':'effect','path':effect,'blend':'screen'})
        if not any(layer['role']=='background' for layer in layers):
            # Use the selected, allowlisted background only. The native M02
            # loader resolves its existing ManaTexture; the generated static
            # mini textures remain 128x128, independent of the movie size.
            selected=next((layer for layer in card.get('layers',[]) if layer.get('slot')=='f02'
                           and layer.get('kind')=='video' and layer.get('path') in paths),None)
            if selected:
                layers.insert(0,{'role':'background','path':selected['path'],
                                 'blend':selected.get('blend','source-over'),'source':'linked-large'})
    for layer in layers:
        stem=PurePosixPath(layer['path']).stem
        if not re.fullmatch(r'[0-9_a-z]+_v',stem) or len(stem[:-2])>22:raise ValueError('小头像动画名称不适配原生接口')
        layer['name']=stem[:-2]
    return {'enabled':enabled,'animated':bool(layers),'layers':layers,'revision':REVISION}


def names(asset_key,motion):
    # Native mini strings are M01..M06. The loader resolves the optional
    # M02/M06 ManaTexture by appending _v. M04 is the transparent player image.
    roles={layer['role']:layer['name'] for layer in motion['layers']}
    return [asset_key+'_b',roles.get('background',''),'',asset_key+'_m','',roles.get('effect','')]
