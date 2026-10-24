"""Android-side import hook for the personal-player V13 build.

Stdlib only. Called after the original, intact legend activation. It never
replaces a club database. A repeated import preserves live progress and edits
the registered player's definition in one SQLite transaction.
"""
import copy
import hashlib
import json
from pathlib import Path
import time
import types

REGISTRY_KEY='personal_player_packages_v1'
MANIFEST='custom-resources/personal-player-studio/players.json'

# Extend the original checked FPS hooks; do not change the engine frame table.
FPS160_BLOB='9737355cca03c9205dd0220c92a3865a4abe73e97690ef776b5a2431a342fc6e'
FPS160_FUNCTIONS={
    'native_payload':'1dda887ce2dfdc64c63dc53040168dbefd0f6769128ae08e53902fb93e2fbcef',
    'validate':'bcb15d61eae99572756d148d1fe2f00bf43e72b76c966dbaa0878e4020e41b4b',
    'install':'4fb544d6f4444e61920f8661ce948d869b6206562ad31d611165cd40f9557018',
    '_request_display_refresh':'4c2119d800c0d827e98a9c3e3d83b7a3835bc950acacf2f2ae1362cc6d773a4a',
    'display_refresh_for_enum':'2f7dfe666e24f8e3da7c44e36cc1bdb7d966da1595f81db45e681eed87a33765',
    'sticky_fps_target':'797496df6e350462c48d7e9b0f95f6a4e2134147567b269f3a82111d2692d411',
    '_write_mailbox':'777676ba2b2dad92f60da5374a0b2334ec283a1dda0eefe8349f57af1515e929',
    '_report':'61f75e061df08552423268f8c271ebb01d189d4be404bf0561ab7dc7645fd80d',
    '_worker':'d89403a8da493833f5f6ab88ad091bc4eb5baea6fff27950cd9fbd9662fa17c1',
}


def prepare_fps160(module):
    """Configure inert Python/native templates before the original worker starts."""
    from personal_binding import code_fingerprint
    if getattr(module,'_studio_fps160',False):return dict(module._studio_fps160)
    if getattr(module,'_started',False):raise ValueError('FPS worker already started before 160 FPS configuration')
    for name,expected in FPS160_FUNCTIONS.items():
        function=getattr(module,name,None)
        if not isinstance(function,types.FunctionType) or code_fingerprint(function.__code__)!=expected:
            raise ValueError('160 FPS runtime interface changed: '+name)
    payload=copy.deepcopy(module.PAYLOAD);blob=bytearray.fromhex(payload['blob_hex'])
    if hashlib.sha256(blob).hexdigest()!=FPS160_BLOB:raise ValueError('160 FPS native template changed')
    if blob[620:624]!=bytes.fromhex('170f8052') or blob[1104:1110]!='120'.encode('utf-16le'):
        raise ValueError('160 FPS native patch sites changed')
    blob[620:624]=bytes.fromhex('17148052')  # MOV W23, #160 in the frame hook.
    blob[1104:1110]='160'.encode('utf-16le')
    payload['blob_hex']=blob.hex()
    def constants(value):
        if type(value) is int and value==120:return 160
        if isinstance(value,tuple):return tuple(constants(v) for v in value)
        return value
    changes={name:getattr(module,name).__code__.replace(co_consts=tuple(constants(v) for v in getattr(module,name).__code__.co_consts))
             for name in ('install','_worker','display_refresh_for_enum')}
    write=module._write_mailbox;report=module._report;request=module._request_display_refresh
    def sticky(desired,focused):return 5 if focused else None
    def mailbox(state,desired,allow):return write(state,5,allow)
    def display(hz):
        result=request(hz)
        supported=result.get('supported_refresh_rates_hz') or []
        rates=[v for v in supported if type(v) in (int,float) and v>0]
        if hz==160 and rates:
            eligible=[v for v in rates if v>=160]
            chosen=min(eligible) if eligible else max(rates)
            if chosen!=hz:result=request(chosen)
        return dict(result,game_target_fps=160)
    def status(root,result):
        return report(root,dict(result,force_160=True,lock_policy='foreground',target_fps=160,actual_render_fps_measured=False))
    module.PAYLOAD=payload
    for name,code in changes.items():getattr(module,name).__code__=code
    module.sticky_fps_target=sticky;module._write_mailbox=mailbox;module._report=status;module._request_display_refresh=display
    module._studio_fps160={'enabled':True,'target_fps':160,'saved_enum':5,'lock_policy':'foreground','original_frame_table_preserved':True,'actual_render_fps_measured':False}
    return dict(module._studio_fps160)


def install_fps_options(document,root):
    options=document.get('frame_rate',{})
    if not options.get('force_160'):return
    try:
        import fps120_runtime
        result=dict(prepare_fps160(fps120_runtime),status='configured')
    except Exception as exc:
        # A runtime mismatch must not prevent the user's game from starting.
        result={'enabled':True,'status':'not_applied','error':str(exc),'actual_render_fps_measured':False}
    destination=Path(root)/'outputs/efootball/personal-fps160-status.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')


def install_package_identity(document):
    if document.get('installation',{}).get('package')!='com.efootball.revival.diyer':return
    import legend_cr7_grants
    from personal_binding import code_fingerprint
    function=legend_cr7_grants._device_root
    if getattr(function,'_studio_coexist',False):return
    if code_fingerprint(function.__code__)!='c72dbd0080b6556425a7d207f69c64437f4a5064bad6b4c506f33ce6d178458c':raise ValueError('Coexist private directory interface changed')
    function.__code__=function.__code__.replace(co_consts=tuple(v.replace('com.efootball.revival.local','com.efootball.revival.diyer') if isinstance(v,str) else v for v in function.__code__.co_consts))
    function._studio_coexist=True


class PackImageService:
    """Serve signed custom banners locally; redirect stock image requests."""
    def __init__(self,root,routes):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from urllib.parse import urlsplit,unquote
        self.root=Path(root).resolve();self.routes={};self.origin=None;self.lock=threading.Lock()
        for request,entry in routes.items():
            relative=Path(entry['path']);path=(self.root/relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(self.root) or not path.is_file():raise ValueError('Pack banner file is missing or outside the resource root')
            raw=path.read_bytes()
            if len(raw)>8*1024*1024 or len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Pack banner checksum failed')
            self.routes[request]=(raw,entry.get('mime','image/jpeg'))
        service=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_HEAD(self):self.serve(False)
            def do_GET(self):self.serve(True)
            def serve(self,body):
                path=unquote(urlsplit(self.path).path);entry=service.routes.get(path)
                if entry:
                    raw,mime=entry;self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','public, max-age=31536000, immutable');self.end_headers()
                    if body:
                        try:self.wfile.write(raw)
                        except (BrokenPipeError,ConnectionResetError):pass
                elif path.startswith('/player-studio/pack-covers/') or not service.origin:
                    self.send_error(404)
                else:
                    self.send_response(302);self.send_header('Location',service.origin.rstrip('/')+'/'+self.path.lstrip('/'));self.send_header('Content-Length','0');self.end_headers()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        threading.Thread(target=self.server.serve_forever,daemon=True,name='personal-pack-images').start()

    def rewrite(self,value):
        from urllib.parse import urlsplit
        pending=[value]
        while pending:
            item=pending.pop()
            if isinstance(item,dict):
                if item.get('type')=='IMAGE_DATA' and isinstance(item.get('url'),str):
                    origin=item['url'];parts=urlsplit(origin)
                    if origin!=self.url and parts.scheme in ('http','https') and parts.netloc:
                        with self.lock:self.origin=origin
                    if self.origin:item['url']=self.url
                pending.extend(item.values())
            elif isinstance(item,list):pending.extend(item)
        return value

    def close(self):self.server.shutdown();self.server.server_close()


def install_pack_images(namespace,document,root):
    routes=document.get('pack_covers',{})
    state=namespace.get('_studio_pack_image_service')
    if not routes:
        if state and state['service']:state['service'].close();state.update(service=None,revision=document['revision'])
        return
    if state and state['revision']==document['revision']:return
    if state and state['service']:state['service'].close()
    service=PackImageService(root,routes)
    if state:state.update(service=service,revision=document['revision']);return
    import threading
    previous=namespace['_local_urls'];local=threading.local()
    state={'service':service,'revision':document['revision']}
    def local_urls(value):
        if getattr(local,'inside',False):return previous(value)
        local.inside=True
        try:value=previous(value)
        finally:local.inside=False
        return state['service'].rewrite(value) if state['service'] else value
    namespace['_local_urls']=local_urls
    if previous.__globals__.get('_local_urls') is previous:previous.__globals__['_local_urls']=local_urls
    namespace['_studio_pack_image_service']=state


def patch_resource_checks(module,document):
    """Retain the original checks, updating only exact packaged resource constants."""
    replacements={}
    for name,old in document.get('original_resource_files',{}).items():
        new=document['resource_files'][name]
        if old['sha256']!=new['sha256']:replacements[old['sha256']]=new['sha256']
        if old['bytes']!=new['bytes']:replacements[old['bytes']]=new['bytes']
    def change(value):
        if type(value) in (str,int):return replacements.get(value,value)
        if isinstance(value,types.CodeType):return value.replace(co_consts=tuple(change(v) for v in value.co_consts))
        if isinstance(value,tuple):return tuple(change(v) for v in value)
        if isinstance(value,list):return [change(v) for v in value]
        if isinstance(value,dict):return {k:change(v) for k,v in value.items()}
        return value
    namespace=vars(module)
    for name,value in list(namespace.items()):
        if isinstance(value,types.FunctionType) and value.__globals__ is namespace:value.__code__=change(value.__code__)
        elif name.endswith('_CHECKS') or any(k in name for k in ('SHA256','FILE_SIZE','FILE_BYTES')):namespace[name]=change(value)


def compact(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def upgrades_from_spent(points):
    spent=0
    for upgrades in range(41):
        if spent==points:return upgrades
        spent+=1+upgrades//4
    raise ValueError('Unrecognized personal-player training ledger')


def _update_owned(current,definition,ledger,groups):
    incoming=definition['owned']
    if current.get('_personal_design_revision')==incoming['_personal_design_revision']:
        return current
    out=copy.deepcopy(current)
    base=list(definition['base_parameters'])
    trained=list(base)
    for group in groups:
        count=upgrades_from_spent(ledger.get(group['id'],0))
        for index in group['indices']:trained[index]=min(105,trained[index]+count)
    cap=incoming['level_info']['level_limit']
    if cap<current['level_info']['level']:
        raise ValueError('New design level cap is below earned player level')
    # Preserve XP, level, point balance, match counters, additional skills,
    # added positions, lock state, acquisition and every unknown runtime field.
    fields=('name','name_en','player_name','_nation_id','initial_base_team_id',
            'initial_base_national_team_id','uniform_number','play_style',
            'initial_booster_id_list','default_rarity','_personal_player_uuid',
            '_personal_design_revision')
    for key in fields:out[key]=copy.deepcopy(incoming[key])
    if '_overall' in incoming:out['_overall']=incoming['_overall']
    out.pop('overall',None);out.pop('default_overall',None)
    out['parameters']=trained
    out['_careerplan_base_parameters']=base
    out['level_info']['level_limit']=cap
    for key in ('_training_auto_allocation','_editor_ability_caps','_level_training_curve'):
        out.pop(key,None)
    return out


def training_hash(conn,owned,cid,serial):
    cursor=conn.execute('select * from careerplan where id=? and serial=? order by rowid',(cid,serial))
    keys=[column[0] for column in cursor.description]
    value={'level_info':owned['level_info'],'careerplan':[dict(zip(keys,row)) for row in cursor],
           'additional_skill_id':owned.get('additional_skill_id'),'additional_position':owned.get('additional_position')}
    return hashlib.sha256(compact(value).encode()).hexdigest()


def apply_weekly_condition(conn,definition):
    selected=definition.get('weekly_condition','auto');grades={'A':4,'B':3,'C':2,'D':1,'E':0}
    if selected not in ('auto',*grades):raise ValueError('Unknown personal weekly condition')
    identity=definition['identity'];mark='personal-weekly-condition:'+identity['package_id'];prefix='editor_live_condition:'
    row=conn.execute('select value from meta where key=?',(mark,)).fetchone();previous=json.loads(row[0]) if row else {}
    for cid in previous.get('ids',[]):
        conn.execute('delete from meta where key=? and value=?',(prefix+str(cid),str(previous['grade'])))
    conn.execute('delete from meta where key=?',(mark,))
    if selected=='auto':return
    ids=sorted({identity['card_id'],*identity.get('previous_card_ids',[])})
    for cid in ids:conn.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',(prefix+str(cid),str(grades[selected])))
    conn.execute('insert into meta values(?,?)',(mark,compact({'ids':ids,'grade':grades[selected]})))

def apply_definitions(conn,document):
    if document.get('format')!='personal-player-native-v1':raise ValueError('Unknown personal player format')
    if conn.in_transaction:raise ValueError('Personal import requires a transaction boundary')
    row=conn.execute('select value from meta where key=?',(REGISTRY_KEY,)).fetchone()
    registry=json.loads(row[0]) if row else {}
    result=[]
    try:
        conn.execute('BEGIN IMMEDIATE')
        apply_game_options(conn,document.get('game_options',{}))
        policy_changed=False
        if document.get('pack_policy',{}).get('allow_china_edition'):
            if conn.execute("select 1 from sqlite_master where type='table' and name='excluded_catalog_ids'").fetchone():
                policy_changed=bool(conn.execute("delete from excluded_catalog_ids where reason='China edition'").rowcount)
        for definition in document['players']:
            apply_weekly_condition(conn,definition)
            identity=definition['identity']
            uid,cid=identity['package_id'],identity['card_id']
            binding=registry.get(uid)
            candidates=[]
            for old_id in identity['previous_card_ids']:
                for oid,serial,raw in conn.execute('select id,serial,json from gameplayers where id=?',(old_id,)):
                    p=json.loads(raw)
                    if p.get('_personal_player_uuid')==uid or binding and (oid,serial)==(binding['card_id'],binding['serial']):
                        candidates.append((oid,serial,p))
                    else:raise ValueError('Personal player ID collision; no changes applied')
            # Pack draws create independent owned copies. Update their design
            # together while keeping each serial's own training and XP.
            for old_id,serial,current in candidates:
                rows=conn.execute('select category,points from careerplan where id=? and serial=?',(old_id,serial)).fetchall()
                ledger={}
                for category,points in rows:ledger[category]=ledger.get(category,0)+int(points)
                owned=_update_owned(current,definition,ledger,document['training_groups'])
                owned=copy.deepcopy(owned)
                owned['gameplayer_id']={'id':cid,'serial':serial}
                if old_id!=cid:
                    if conn.execute('select 1 from gameplayers where id=? and serial=?',(cid,serial)).fetchone():
                        raise ValueError('Updated card ID collides with another owned instance')
                    from legend_card_style import remap_references
                    pairs={(old_id,serial):cid}
                    for squad_id,raw in conn.execute('select squad_id,json from squads').fetchall():
                        original=json.loads(raw);mapped=remap_references(original,pairs)
                        if mapped!=original:conn.execute('update squads set json=? where squad_id=?',(compact(mapped),squad_id))
                    for table in ('careerplan','warehouse','rentals'):
                        if conn.execute("select 1 from sqlite_master where type='table' and name=?",(table,)).fetchone():
                            conn.execute(f'update {table} set id=? where id=? and serial=?',(cid,old_id,serial))
                    conn.execute('update owned_identity_aliases set id=? where id=? and new_serial=?',(cid,old_id,serial))
                if owned!=current or old_id!=cid:
                    checkpoint='personal-before:'+uid+':'+str(serial)+':'+current.get('_personal_design_revision','legacy')
                    conn.execute('insert or ignore into meta values(?,?)',(checkpoint,compact(current)))
                    conn.execute('update gameplayers set id=?,json=? where id=? and serial=?',(cid,compact(owned),old_id,serial))
                action='preserved-progress'
                result.append({'package_id':uid,'card_id':cid,'serial':serial,'status':action})
            if not candidates and not binding:
                # V13 uses a globally unique owned serial, including across
                # different cards. Follow its allocator and legacy aliases.
                serial=conn.execute('select coalesce(max(serial),0)+1 from gameplayers where serial between 1 and 2147483646').fetchone()[0]
                version=conn.execute("select value from meta where key='owned_identity_version'").fetchone()
                if version and version[0]=='1':
                    while conn.execute('select 1 from owned_identity_aliases where old_serial=? limit 1',(serial,)).fetchone():serial+=1
                if serial>=2147483647:raise ValueError('Owned serial range exhausted')
                owned=copy.deepcopy(definition['owned'])
                owned['gameplayer_id']={'id':cid,'serial':serial}
                conn.execute('insert into gameplayers(id,serial,json,source,acquired_at) values(?,?,?,?,?)',
                             (cid,serial,compact(owned),'personal-player-studio',str(int(time.time()))))
                for category,points in definition['allocation'].items():
                    conn.execute('insert into careerplan(id,serial,category,points,at) values(?,?,?,?,?)',
                                 (cid,serial,category,points,'personal-initial-import'))
                conn.execute('insert or ignore into owned_identity_aliases(id,old_serial,new_serial) values(?,?,?)',(cid,0,serial))
                action='granted'
                result.append({'package_id':uid,'card_id':cid,'serial':serial,'status':action})
            elif not candidates:
                # Still refresh the pack catalogue below, but never grant a
                # sold/released registered player again during an update.
                result.append({'package_id':uid,'status':'registered-instance-absent'})
                serial=binding['serial']
                owned=definition['owned']
            catalog=copy.deepcopy(definition['owned'])
            catalog['gameplayer_id']={'id':cid,'serial':0}
            catalog['parameters']=list(definition['base_parameters'])
            catalog['level_info'].update(level=1,exp_total=0,exp_current_level=0,customize_point=0)
            payload=compact(catalog)
            fingerprint=hashlib.sha256(payload.encode()).hexdigest()
            existing=conn.execute('select payload from managed_cards where card_id=?',(str(cid),)).fetchone()
            if existing and json.loads(existing[0]).get('_personal_player_uuid')!=uid:
                raise ValueError('Personal catalogue ID collides with an original definition')
            conn.execute('insert into managed_cards(card_id,fingerprint,payload,card_type,subtype,evidence) values(?,?,?,?,?,?) '
                         'on conflict(card_id) do update set fingerprint=excluded.fingerprint,payload=excluded.payload,card_type=excluded.card_type,subtype=excluded.subtype,evidence=excluded.evidence',
                         (str(cid),fingerprint,payload,definition['card_type'],definition['card_series'],'personal-player-studio:'+uid))
            conn.execute('insert into managed_serials(card_id,next_serial) values(?,?) on conflict(card_id) do update set next_serial=max(next_serial,excluded.next_serial)',(str(cid),serial+1))
            registry[uid]={**(binding or {}),'card_id':cid,'serial':binding['serial'] if binding else serial,'design_revision':owned['_personal_design_revision']}
            if not binding:
                registry[uid]['training_sha256']=training_hash(conn,owned,cid,serial)
        pack_revision=conn.execute("select value from meta where key='personal_pack_revision_v1'").fetchone()
        if policy_changed or not document.get('revision') or not pack_revision or pack_revision[0]!=document['revision']:
            apply_packs(conn,document.get('packs',[]))
            if document.get('revision'):conn.execute("insert into meta values('personal_pack_revision_v1',?) on conflict(key) do update set value=excluded.value",(document['revision'],))
        conn.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',(REGISTRY_KEY,compact(registry)))
        conn.commit()
    except BaseException:
        conn.rollback();raise
    return result


def apply_game_options(conn,options):
    """Apply an explicitly saved revision once; later matches keep progressing."""
    if not options.get('enabled'):return
    revision=options.get('revision')
    if not revision:raise ValueError('AI division settings are missing their revision')
    key='personal_ai_division_revision_v1'
    old=conn.execute('select value from meta where key=?',(key,)).fetchone()
    if old and old[0]==revision:return
    import ai_division
    state=ai_division.state(conn)
    state.update({k:options[k] for k in ('division','points','matches','wins','draws','losses')})
    state['best']=min(state.get('best',10),options['division'])
    ai_division.save(conn,state)
    conn.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',(key,revision))


def apply_packs(conn,packs):
    """Runs inside the same import transaction. Never clears draw receipts/consumption."""
    key='personal_pack_registry_v1';row=conn.execute('select value from meta where key=?',(key,)).fetchone()
    registry=json.loads(row[0]) if row else {}
    row=conn.execute("select value from meta where key='agent_price_list'").fetchone()
    prices=json.loads(row[0]) if row else []
    row=conn.execute("select value from meta where key='league_position_agent_ids'").fetchone()
    active=json.loads(row[0]) if row and row[0] else []
    selected={p['uuid'] for p in packs};skipped=[]
    has_exclusions=conn.execute("select 1 from sqlite_master where type='table' and name='excluded_catalog_ids'").fetchone()
    excluded={str(r[0]):r[1] for r in conn.execute('select card_id,reason from excluded_catalog_ids')} if has_exclusions else {}
    for uid,aid in registry.items():
        if uid not in selected:
            conn.execute('update managed_agents set enabled=0 where agent_id=?',(aid,))
            conn.execute('delete from agents where agent_id=?',(aid,))
            prices=[p for p in prices if p['agent_id']!=aid];active=[v for v in active if v!=aid]
    for pack in packs:
        uid,aid=pack['uuid'],pack['agent_id']
        if uid in registry and registry[uid]!=aid:raise ValueError('Permanent pack identity changed')
        existing=conn.execute('select 1 from agents where agent_id=?',(aid,)).fetchone()
        if existing and registry.get(uid)!=aid:raise ValueError('Personal pack ID collision')
        members=[]
        for member in pack['members']:
            cid=str(member['card_id'])
            if cid in excluded:
                skipped.append({'pack':pack['name'],'card_id':cid,'reason':excluded[cid]});continue
            payload=compact(member['payload']);fingerprint=hashlib.sha256(payload.encode()).hexdigest()
            conn.execute('insert or ignore into managed_cards values(?,?,?,?,?,?)',(cid,fingerprint,payload,member['card_type'],member['subtype'],'personal-pack:'+uid))
            if not conn.execute('select 1 from managed_cards where card_id=?',(cid,)).fetchone():
                raise ValueError('Pack member is excluded by this version: '+cid)
            members.append(member)
        enabled=pack['enabled'] and bool(members)
        conn.execute('insert into managed_agents values(?,?,?,?,?) on conflict(agent_id) do update set name=excluded.name,enabled=excluded.enabled,replacement=excluded.replacement,mode=excluded.mode',
                     (aid,pack['name'],int(enabled),int(pack['replacement']),'PERSONAL_FREE'))
        conn.execute('delete from managed_members where agent_id=?',(aid,))
        conn.executemany('insert into managed_members values(?,?,?)',[(aid,m['card_id'],m['weight']) for m in members])
        if enabled:
            conn.execute('insert into agents values(?,?) on conflict(agent_id) do update set json=excluded.json',(aid,compact(pack['agent'])))
        else:conn.execute('delete from agents where agent_id=?',(aid,))
        prices=[p for p in prices if p['agent_id']!=aid]+([pack['price']] if enabled else [])
        if not enabled:active=[v for v in active if v!=aid]
        elif active and aid not in active:active.append(aid)
        registry[uid]=aid
    conn.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',('personal_pack_skipped_v1',compact(skipped)))
    if skipped:
        import logging
        logging.warning('Personal packs skipped %s version-excluded cards: %s',len(skipped),compact(skipped))
    for name,value in ((key,registry),('agent_price_list',prices)):
        conn.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',(name,compact(value)))
    conn.execute("insert into meta values('league_position_agent_ids',?) on conflict(key) do update set value=excluded.value",(compact(active),))


def install(namespace):
    """Install through the original gateway stub, without changing its loader."""
    original=namespace['initialize']
    configured={'revision':None,'document':None,'wrapped':False,'display':False}
    def initialize(root,*args,**kwargs):
        root=Path(root)
        path=root/MANIFEST
        if not path.is_file():raise RuntimeError('Personal-player manifest is missing')
        document=json.loads(path.read_text(encoding='utf8'))
        install_pack_images(namespace,document,root)
        import _protected_runtime
        _protected_runtime.install_root(root)
        install_package_identity(document)
        install_fps_options(document,root)
        import legends_v10
        if document.get('native_binding'):
            import personal_binding
            personal_binding.install(legends_v10,document['native_binding'],root)
        revision=document['revision']
        if revision!=configured['revision']:
            resources=document['resource_files']
            patch_resource_checks(legends_v10,document)
            for row in legends_v10._SOURCE_CHECKS:
                row.update(resources[row['name']])
            for row in legends_v10._ACTIVE_CHECKS:
                row.update(resources[row['source']])
            # The original first-grant checks for its three legends also
            # verify the same CPK/container bytes. Their player rows are kept
            # byte-identical inside our extended files.
            for name in ('_RESOURCE_CHECKS','_ZIDANE_RESOURCE_CHECKS'):
                for row in getattr(legends_v10,name,()):
                    filename=Path(row['path']).name
                    if filename in resources:row.update(resources[filename])
            legends_v10._source_verified.clear()
            legends_v10._active_fingerprint=None
            configured['revision']=revision
            configured['document']=document
        if not configured['wrapped']:
            previous=legends_v10.activate
            def activate(resource_root,conn):
                status=previous(resource_root,conn)
                if status.get('status')!='ready':return status
                imported=apply_definitions(conn,configured['document'])
                coaches=apply_coaches(conn,configured['document'].get('coaches',[]))
                status=dict(status,personal_players=imported,personal_coaches=coaches)
                destination=Path(resource_root)/'outputs/efootball/personal-player-status.json'
                destination.write_text(compact(status),encoding='utf8')
                return status
            legends_v10.activate=activate
            configured['wrapped']=True
        # V16 supplies installed_version as a second startup argument.
        # Preserve it and any future positional/keyword arguments verbatim.
        result=original(root,*args,**kwargs)
        if not configured['display']:
            install_display_previews(lambda:configured['document'],namespace.get('_logic'),root)
            configured['display']=True
        return result
    namespace['initialize']=initialize


def developed_personal(player,definition):
    maximum=definition.get('maximum_development')
    if not maximum:return player
    out=copy.deepcopy(player);out['parameters']=list(maximum['parameters'])
    out['_preview_base_parameters']=list(definition['base_parameters'])
    out['_developed_preview']=maximum['level']
    out['overall']=out['default_overall']=out['_overall']=maximum['overall']
    out['_draw_preview_overall_v1']=maximum['overall']
    out['level_info']=dict(out.get('level_info') or {},level=maximum['level'],level_limit=maximum['level'],
                           exp_total=0,exp_current_level=0,exp_to_next_level=0,customize_point=0)
    return out


def install_display_previews(document,logic=None,root=None):
    """Personal card display copies; owned training is never overwritten."""
    import developed_preview,club_store,gate_logic,threading,editor_progression
    state=threading.local();old_developed=developed_preview.developed;old_wire=club_store.wire_player
    def definition(player):
        uid=player.get('_personal_player_uuid');cid=(player.get('gameplayer_id') or {}).get('id')
        return next((d for d in document()['players'] if d['identity']['package_id']==uid or cid in d['identity']['previous_card_ids']),None)
    def developed(player,boosts=None):
        own=definition(player)
        return developed_personal(player,own) if own else old_developed(player,boosts)
    def wire(player,*args,**kwargs):
        out=old_wire(player,*args,**kwargs)
        preview_context=getattr(state,'preview',False)
        if preview_context or getattr(state,'draw',False) or player.get('_developed_preview') or '_draw_preview_overall_v1' in player:
            own=definition(player)
            if own and own.get('maximum_development'):
                out['overall']=out['default_overall']=own['maximum_development']['overall']
            if document().get('game_version') in ('V14','V15') or document().get('adapter_family')=='V14':
                # The native JSON reader consumes disp_overall. The similarly
                # named overall/default_overall keys are ignored by that reader,
                # allowing it to recalculate already developed preview abilities.
                if own and own.get('maximum_development'):score=own['maximum_development']['overall']
                else:
                    preview=old_developed(player,{}) if not player.get('_developed_preview') else player
                    preview=copy.deepcopy(preview)
                    # Native player boosters are applied separately from the
                    # training parameters. Include unconditional effects in the
                    # rating copy, without writing them twice into live stats.
                    params=preview.get('parameters') or []
                    for bid in set(params[144:147]):
                        booster=document().get('preview_boosters',{}).get(str(bid))
                        if not booster or booster.get('conditional'):continue
                        for index,amount in booster['effects'].items():
                            i=int(index);params[i]=max(1,min(127,params[i]+amount))
                    developed_preview.apply_display_overall(preview)
                    score=preview.get('overall',player.get('_draw_preview_overall_v1'))
                if type(score) is int and 1<=score<=127:
                    out['disp_overall']=out['disp_max_overall']=score
                    if document().get('native_binding',{}).get('profile',{}).get('overall_hook',{}).get('global_preview'):
                        import personal_binding
                        personal_binding.set_preview_score(int((player.get('gameplayer_id') or {})['id']),score)
        return out
    developed_preview.developed=developed;club_store.wire_player=wire
    previous_cap=editor_progression.card_level_cap
    previous_state=editor_progression.state
    def card_level_cap(conn,player):
        own=definition(player)
        return own['owned']['level_info']['level_limit'] if own else previous_cap(conn,player)
    def progression_state(conn,player):
        result=previous_state(conn,player);own=definition(player)
        if own:result['level_cap']=own['owned']['level_info']['level_limit']
        return result
    editor_progression.card_level_cap=card_level_cap
    editor_progression.state=progression_state
    if document().get('game_version') in ('V14','V15') or document().get('adapter_family')=='V14':
        import draw_presentation,managed_card_pool
        draw_presentation.response_fields=lambda players:draw_response_fields(players,document().get('draw_profiles',{}),document().get('card_series_by_id',{}))
        old_decorate=managed_card_pool.decorate_agents
        def decorate_agents(*args,**kwargs):
            previous=getattr(state,'preview',False);state.preview=True
            try:return old_decorate(*args,**kwargs)
            finally:state.preview=previous
        managed_card_pool.decorate_agents=decorate_agents
    # Some original services import this function directly before startup.
    # Update those exact aliases as well; foreign players keep the original cap.
    import sys
    for module in tuple(sys.modules.values()):
        for key,value in tuple(vars(module).items()) if isinstance(module,types.ModuleType) else ():
            if value is previous_cap:setattr(module,key,card_level_cap)
            elif value is previous_state:setattr(module,key,progression_state)
    gate_class=type(logic) if logic is not None else gate_logic.GateLogic
    previous=gate_class._use_agent
    def use_agent(self,*args,**kwargs):
        old=getattr(state,'draw',False);state.draw=True
        try:
            result=previous(self,*args,**kwargs)
            response=args[0] if args else kwargs.get('resp')
            if isinstance(response,dict):
                sanitize_draw_effects(response,document())
                if root is not None:
                    summary={'effect_list':response.get('effect_list'),'special':response.get('special_gacha_effect_player_id'),
                             'players':[(r.get('gameplayer',{}).get('gameplayer_id') or {}) for r in response.get('gameplayer_list',[])],
                             'display_ratings':[r.get('gameplayer',{}).get('disp_overall') for r in response.get('gameplayer_list',[])]}
                    (Path(root)/'outputs/efootball/personal-draw-display.json').write_text(compact(summary),encoding='utf8')
            return result
        finally:state.draw=old
    gate_class._use_agent=use_agent
    for module in tuple(sys.modules.values()):
        for key,value in tuple(vars(module).items()) if isinstance(module,types.ModuleType) else ():
            if value is old_developed:setattr(module,key,developed)
            elif value is old_wire:setattr(module,key,wire)
    if root is not None:
        (Path(root)/'outputs/efootball/personal-display-bindings.json').write_text(compact({
            'configured':True,'game_logic_class':gate_class.__module__+'.'+gate_class.__name__,
            'owned_progress_mutated':False}),encoding='utf8')


def sanitize_draw_effects(response,document):
    """Do not inherit the captured revival-pair scene for personal packs.

    The original BP_PA_Gate reads card index 1/2 when REVIVAL_SOLO/TWO is set.
    A personal single draw only has index 0; the captured flag otherwise hides
    the side position/club and sends card parts to the wrong scene slots.
    """
    identities={cid for d in document['players'] for cid in d['identity']['previous_card_ids']}
    personal=any((row.get('gameplayer',{}).get('gameplayer_id') or {}).get('id') in identities
                 for row in response.get('gameplayer_list',[]))
    if personal and isinstance(response.get('effect_list'),list):
        response['effect_list']=[v for v in response['effect_list'] if not (isinstance(v,str) and v.startswith('REVIVAL_'))]
        # V14 projects its own response effects instead of retaining the old
        # capture. Its Big Time branch deliberately emits no scene. Restore
        # the exact BT sequence verified with the unchanged acquisition assets.
        if (document.get('game_version') in ('V14','V15') or document.get('adapter_family')=='V14') and not response['effect_list']:
            ids={(row.get('gameplayer',{}).get('gameplayer_id') or {}).get('id') for row in response.get('gameplayer_list',[])}
            own=next((d for d in document['players'] if ids.intersection(d['identity']['previous_card_ids'])),None)
            effects=(document.get('draw_profiles') or {}).get(own.get('card_type')) if own else None
            if effects:response['effect_list']=list(effects)


def apply_coaches(conn,coaches):
    key='personal_coaches_v1';row=conn.execute('select value from meta where key=?',(key,)).fetchone()
    registry=json.loads(row[0]) if row else {};report=[]
    with conn:
        serial=conn.execute('select coalesce(max(serial),0) from coaches').fetchone()[0]
        for definition in coaches:
            uid=definition['uuid'];cid=definition['id'];previous=registry.get(uid)
            if previous and previous['id']!=cid:raise ValueError('个人教练永久身份改变')
            if previous:
                record=conn.execute('select json from coaches where coach_id=? and serial=?',(cid,previous['serial'])).fetchone()
                if record is None:
                    report.append({'uuid':uid,'status':'registered-instance-absent'});continue
                data=json.loads(record[0]);incoming=definition['payload']
                for field in ('name','name_en','age','ability_id','possession','short_counter','long_counter','side_attack','long_ball','_personal_coach_revision'):
                    data[field]=copy.deepcopy(incoming[field])
                data['is_coach_texture_use']=incoming.get('is_coach_texture_use','NO')
                conn.execute('update coaches set json=? where coach_id=? and serial=?',(compact(data),cid,previous['serial']))
            else:
                if conn.execute('select 1 from coaches where coach_id=?',(cid,)).fetchone():raise ValueError('个人教练编号与存档冲突')
                serial+=1;data=copy.deepcopy(definition['payload']);data['coach_id']={'id':cid,'serial':serial}
                conn.execute('insert into coaches values(?,?,?)',(cid,serial,compact(data)));registry[uid]={'id':cid,'serial':serial}
            report.append({'uuid':uid,'id':cid,'serial':registry[uid]['serial'],'status':'ready'})
        conn.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',(key,compact(registry)))
    return report


def draw_response_fields(players,profiles,series_by_id=None):
    """Select the actual card series before the broader LEGENDARY type.

    V14's supplied implementation gives native_legendary priority over BT's
    metadata. Both series use that broad type, but have distinct opening enums.
    Native auto selection is independent of the owned result identities.
    """
    special={'id':0,'serial':0};effects=[];pickups=[];seen=set()
    defaults={'BigTime':['WIN_SCREEN','SPOTLIGHT_BIGWIN','RED_CARPET','OPENING_BIGTIME'],
              'Epic':['WIN_SCREEN','SPOTLIGHT_WIN','RED_CARPET','OPENING_EPIC'],
              'Legendary':['WIN_SCREEN','SPOTLIGHT_WIN','RED_CARPET','OPENING_EPIC'],
              'ShowTime':['WIN_SCREEN','SPOTLIGHT_WIN','RED_CARPET','OPENING_SHOWTIME']}
    for player in players:
        gid=player['gameplayer_id'];meta=player.get('_draw_gacha_v1') or {}
        kind=str(meta.get('card_type','')).replace(' ','').replace('_','').lower()
        series={'bigtime':'BigTime','epic':'Epic','legendary':'Legendary','showtime':'ShowTime'}.get(kind)
        series=(series_by_id or {}).get(str(gid['id']),series)
        if not kind and player.get('type')=='LEGENDARY':series='Legendary'
        if not special['id'] and series:
            special={'id':int(gid['id']),'serial':int(gid.get('serial') or 0)}
            effects=list(profiles.get(series,defaults[series]))
        pid=int(gid['id'])
        if meta.get('pickup') and pid not in seen:
            seen.add(pid);pickups.append({'id':pid,'serial':0})
    # The native auto-selection sentinel works with the frozen receipt order,
    # including multi draws. An owned serial is not a scene-slot identifier.
    # Never change the actual acquired identities or their order here.
    if profiles.get('player_selection')=='auto' or (len(players)==1 and profiles.get('single_player_selection')=='auto'):
        special={'id':0,'serial':0}
    return {'effect_list':effects,'special_gacha_effect_player_id':special,'pickup_cardtype_list':pickups}
