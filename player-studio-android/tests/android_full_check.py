"""Full handset CPU pipeline; debug-only documents supply original input bytes."""
from pathlib import Path
import copy,hashlib,json,shutil,time,uuid

def run(home,native_dir,fixtures,resume=False):
    cache_root=Path(home)/'library'
    assert Path(home).name=='studio' and Path(home).parent.name=='files'
    if cache_root.exists() and not resume:shutil.rmtree(cache_root)
    # Each run starts with a fresh imported database too: an already committed
    # database correctly skips extraction during an ordinary repeated import.
    imported_root=Path(home)/'data/game-databases'
    if imported_root.exists() and not resume:shutil.rmtree(imported_root)
    if not resume:(Path(home)/'data/active-game.json').unlink(missing_ok=True)
    from android_backend import start,_server
    import android_backend
    from java import jclass
    start(home,native_dir);server=android_backend._server;bridge=jclass('com.playerstudio.editor.QaBridge')
    import app
    sources=json.loads(str(bridge.originals(home)));phase=[]
    def wait(obj,label,timeout=1200):
        last=None;deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            state=obj.status()
            if state.get('message')!=last:last=state.get('message');print(label+': '+str(last),flush=True)
            if state['phase']!='working':assert state['phase']=='done',state;return state
            time.sleep(1)
        raise RuntimeError(label+' timed out')
    if not resume:
        server.game_import.start({'apk':sources['main'],'companion':sources['companion']});imported=wait(server.game_import,'APK database and resource import')
    else:imported={}
    library=server.library
    # Verify the real extracted cache, then use equal read-only proxy files to
    # keep the small test VM's disk free. Production has no proxy dependency.
    cache=json.loads(str(bridge.cacheManifest()));checked=0
    for ident,item in cache.items():
        if not ident.startswith('cache-'):continue
        if not resume:
            path=library.containers/item['name'];assert path.stat().st_size==item['size']
            with path.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256'],path.name
        checked+=1
    bridge.useEquivalentReadOnlyCache(str(library.containers));print('Extracted original cache matched '+str(checked)+' files',flush=True)
    for path in library.containers.glob('*.utoc'):
        raw=path.read_bytes()
        if raw[:16]!=b'-==--==--==--==-':raise ValueError('QA alias mismatch '+path.name+' size='+str(len(raw))+' prefix='+raw[:24].hex())
    row=library.player('52777095109189');payload=row['payload'];params=payload['parameters']
    ids=[row[k] for k in ('portrait','thumbnail','auto_model') if row.get(k)]
    converted=library.convert({'ids':ids})['results'];model=converted[row['auto_model']];portrait=converted[row['portrait']]
    assert not model.get('error') and not portrait.get('error')
    print('Original Firmino portrait and head decoded on Android',flush=True)
    card=library.card(row['id']);assert card and not card.get('missing'),card.get('missing')
    p=app.default_project();p['package_id']=str(uuid.uuid4());p['identity'].update(name='Android QA Firmino',position=row['position'],height_cm=params[47],weight_kg=params[48],age=params[46] or 22,
        team_id=row['identity_names']['team']['id'],nation_id=row['identity_names']['nation']['id'],team=row['identity_names']['team']['name'],nationality=row['identity_names']['nation']['name'])
    p.update(display_name='Android QA Firmino',source_player={'id':row['id'],'name':row['name'],'name_en':row['name_en'],'base_id':row['base_id'],'original_payload':payload},card_type=row['card_type'],card_series=row['card_type'],max_level=row['level_limit'] or 1,initial_level=1,
        native_card=card,native_card_disabled=False,base_abilities={i:params[int(i)] for i in server.catalog['ABILITIES']},
        innate_skills=payload['_studio_skill_ids'],additional_skills=[],position_aptitudes={pos:params[i+1] for i,pos in enumerate(server.catalog['APTITUDES'])},play_style={'attack':payload['play_style'][0],'defense':payload['play_style'][1]},
        training={g['id']:0 for g in server.catalog['training_groups']},booster_ids=[0,0])
    p['appearance'].update(portrait=portrait['asset_id'],portrait_fit='native',photo_zoom=1,photo_x=0,photo_y=0,hide_portrait=False)
    p['native_art']={'portrait':portrait}
    p['model'].update(asset=model['asset_id'],native_source=model,physique=row['appearance_profile']['physique'],skin_tone=row['appearance_profile']['skin_tone'] or 1,
        appearance_source_id=row['appearance_profile']['source_id'],torso_length=14-row['appearance_profile']['physique']['leg_length'])
    if row.get('thumbnail'):
        thumbnail=converted[row['thumbnail']];p['appearance'].update(thumbnail_image=thumbnail['asset_id'],thumbnail_mode='image');p['native_art']['thumbnail']=thumbnail
    p=app.normalize_project(p);server.store.save_player(p);server.store.save(p)
    server.native_package.reference_model()
    server.native_package.start({'project':p,'selected_ids':[p['package_id']],'packs':[],'pack_ids':[],'coach_ids':[],'apk':sources['main']})
    result=wait(server.native_package,'Full original-size APK generation');report=result['result']['report']
    assert report['native_art'][0]['skin_tone']['mode']=='preserved-original'
    summary={'android_native_full_pipeline':'passed','cache_files_verified':checked,'database':imported.get('result'),
        'model':{'materials':model.get('materials'),'textured_materials':model.get('textured_materials')},
        'apk_bytes':result['result']['size'],'signature':report['signature'],'skin':report['native_art'][0]['skin_tone'],
        'original_sources':'debug-only read-only documents; all conversion, database import, APK composition and signing executed inside Android',
        'in_game_tested':False}
    (Path(home)/'android-full-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    return json.dumps(summary,ensure_ascii=False)
