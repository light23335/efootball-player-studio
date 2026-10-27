import base64
import contextlib
import copy
import hashlib
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
import app


class StudioTests(unittest.TestCase):
    def test_preset_catalogue_only_references_separable_design_layers(self):
        library=app.NativeLibrary(app.RESOURCE,Path(__file__).absolute().parents[2]/'球员工坊-V14',self.store)
        presets=library.presets
        self.assertEqual(len(presets.rows),sum(presets.catalog['counts'].values()))
        self.assertGreaterEqual(presets.catalog['counts']['BigTime'],60)
        self.assertGreaterEqual(presets.catalog['counts']['Epic'],25)
        for row in presets.rows.values():
            self.assertTrue(all(l['slot'] in ('f01','f02','f03','f04','f05','f07','f10') for l in row['layers']))
            self.assertTrue(all('/Variation2022/' in l['path'] or '/Player/0000_f01_' in l['path'] or l['kind']=='video' for l in row['layers']))
            library.player(row['source_id'])
        self.assertEqual(presets.search({'kind':'Epic'})['total'],presets.catalog['counts']['Epic'])
        with self.assertRaises(ValueError):presets.get('not-a-preset')
        with self.assertRaises(ValueError):presets.previews(['x']*13)
        incomplete=next(r for r in presets.rows.values() if r.get('available') is False)
        with self.assertRaises(ValueError):presets.apply({'id':incomplete['id']})

    def test_card_date_validation_and_personal_project_roundtrip(self):
        p=app.default_project();p['appearance']['card_date']='2000-02-29';p['appearance']['card_rarity']=5
        p['appearance']['hide_portrait']=True;p['preview']={'training_position':'GK'}
        self.assertEqual(app.normalize_project(p)['appearance']['card_date'],'2000-02-29')
        exported=self.store.export_project(p);other=app.Store(self.root/'date-restored')
        self.assertEqual(other.import_project(exported['path'])['appearance'],app.normalize_project(p)['appearance'])
        self.assertEqual(other.project['preview']['training_position'],'GK')
        p['appearance']['card_date']='2001-02-29'
        with self.assertRaises(ValueError):app.normalize_project(p)

    def test_restart_launch_token_takes_precedence_over_old_cookie(self):
        from types import SimpleNamespace
        request=SimpleNamespace(headers={'Cookie':'studio_session=old-session'},path='/?token=current-session',server=SimpleNamespace(token='current-session'))
        self.assertTrue(app.Handler.authenticated(request))
        request.path='/?token=wrong-session';self.assertFalse(app.Handler.authenticated(request))
        request.path='/';request.headers={'Cookie':'studio_session=current-session'}
        self.assertTrue(app.Handler.authenticated(request))

    def test_custom_boosters_roundtrip_and_slot_constraints(self):
        p=app.default_project();p['custom_boosters']=[{'id':1000,'label':'速度大师','effects':{'34':7,'20':-2}}];p['booster_ids']=[0,1000]
        q=app.normalize_project(p);self.assertEqual(q['custom_boosters'][0]['effects'],{'34':7,'20':-2})
        self.assertEqual(app.normalize_project(q)['custom_boosters'][0]['uuid'],q['custom_boosters'][0]['uuid'])
        p['booster_ids']=[1000,0]
        self.assertEqual(app.normalize_project(p)['booster_ids'][0],1000)
        p['booster_ids']=[0,1000];p['custom_boosters'][0]['effects']['34']=21
        with self.assertRaises(ValueError):app.normalize_project(p)

    def test_verified_neymar_level_and_native_identity_aliases(self):
        from native_library import NativeLibrary
        library=NativeLibrary(app.RESOURCE,Path(__file__).absolute().parents[2]/'球员工坊-V14',self.store)
        neymar=library.player('370536760778144')
        self.assertEqual(neymar['level_limit'],19);self.assertEqual(neymar['identity_names']['nation']['name'],'巴西')
        self.assertEqual(neymar['identity_names']['team']['name'],'巴西')
        self.assertTrue(neymar['auto_model']);self.assertTrue(neymar['portrait'])
        henry=library.player('88046312750111');self.assertTrue(henry['portrait']);self.assertTrue(henry['auto_model'])

    def setUp(self):
        root=Path(__file__).absolute().parents[2]/'.work'/'studio-unit'
        root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=app.Store(self.root/'data')

    def test_original_permanent_identity_is_kept(self):
        p=self.store.project
        p['package_id']='f64c7ce3-bfe9-4d99-92ec-06952636dfb4'
        p['future_progress_field']={'keep':True}
        p['identity']['name']='测试球员'
        self.store.save(p)
        reloaded=app.Store(self.root/'data')
        self.assertEqual(reloaded.project['identity']['name'],'测试球员')
        self.assertEqual(reloaded.project['future_progress_field'],{'keep':True})
        self.assertEqual(reloaded.project['package_id'],p['package_id'])

    def test_project_bundle_round_trip_carries_assets(self):
        # Valid minimal PNG generated from an embedded tiny fixture.
        data=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWj8AAAAASUVORK5CYII=')
        p=copy.deepcopy(self.store.project)
        asset=self.store.import_screenshot('data:image/png;base64,'+base64.b64encode(data).decode())
        p['appearance']['portrait']=asset['id']
        p['base_abilities']['20']=94
        p['training']['SHOOT']=8
        exported=self.store.export_project(p)
        other=app.Store(self.root/'other')
        restored=other.import_project(exported['path'])
        self.assertEqual(restored['base_abilities']['20'],94)
        self.assertEqual(restored['training']['SHOOT'],8)
        self.assertEqual(restored['package_id'],p['package_id'])
        self.assertEqual((other.root/'assets'/asset['id']).read_bytes(),data)

    def test_unknown_skills_rejected_but_additional_overflow_preserved(self):
        p=copy.deepcopy(self.store.project);p['innate_skills']=[9999]
        with self.assertRaises(ValueError):app.normalize_project(p)
        p['innate_skills']=[];p['additional_skills']=[int(k) for k in app.CATALOG['PARAMETER_BY_SKILL'] if '预留' not in app.CATALOG['SKILL_LABELS'].get(str(k),'')][:11]
        self.assertEqual(app.normalize_project(p)['additional_skills'],p['additional_skills'])

    def test_ten_additional_skills_save_and_reopen(self):
        p=copy.deepcopy(self.store.project);p['innate_skills']=[]
        p['additional_skills']=[int(k) for k in app.CATALOG['PARAMETER_BY_SKILL'] if '预留' not in app.CATALOG['SKILL_LABELS'].get(str(k),'')][:10]
        normalized=app.normalize_project(p)
        self.assertEqual(normalized['additional_skills'],p['additional_skills'])
        self.store.save(normalized)
        self.assertEqual(app.Store(self.store.root).project['additional_skills'],p['additional_skills'])

    def test_twenty_innate_and_ten_additional_save_without_reclassification(self):
        p=copy.deepcopy(self.store.project)
        skills=[int(k) for k in app.CATALOG['PARAMETER_BY_SKILL'] if '预留' not in app.CATALOG['SKILL_LABELS'].get(str(k),'')]
        p['innate_skills']=skills[:20];p['additional_skills']=skills[20:30]
        self.store.save(app.normalize_project(p))
        restored=app.Store(self.store.root).project
        self.assertEqual(restored['innate_skills'],skills[:20])
        self.assertEqual(restored['additional_skills'],skills[20:30])
        p['innate_skills']=skills[:21];p['additional_skills']=skills[21:32]
        normalized=app.normalize_project(p)
        self.assertEqual(normalized['innate_skills'],skills[:21])
        self.assertEqual(normalized['additional_skills'],skills[21:32])

    def test_second_booster_slot_does_not_shift(self):
        p=copy.deepcopy(self.store.project);p['booster_ids']=[0,201]
        self.assertEqual(app.normalize_project(p)['booster_ids'],[0,201])
        p['booster_ids']=[201,201]
        with self.assertRaises(ValueError):app.normalize_project(p)

    def test_big_time_native_class_and_old_project_roundtrip(self):
        library=app.NativeLibrary(app.RESOURCE,Path(__file__).absolute().parents[1],self.store)
        big=library.player('89138556575063')
        self.assertEqual(big['card_type'],'BigTime')
        self.assertEqual(big['payload']['_studio_native_card_class'],'Epic')
        self.assertTrue(big['payload']['_studio_card_label'].startswith('Big Time'))
        self.assertNotIn(big['id'],[r['id'] for r in library.search({'kind':'Epic','query':big['id']})['rows']])
        self.assertEqual(library.search({'kind':'BigTime','query':big['id']})['total'],1)
        p=copy.deepcopy(self.store.project);p.update(card_type='Epic',card_series='BigTime')
        p['training']['SHOOT']=3
        exported=self.store.export_project(p);restored=self.store.import_project(exported['path'])
        self.assertEqual(restored['card_type'],'BigTime');self.assertEqual(restored['card_series'],'BigTime')
        self.assertEqual(restored['package_id'],p['package_id']);self.assertEqual(restored['training']['SHOOT'],3)

    def test_saved_players_remain_independent_and_recompute_overall(self):
        first=copy.deepcopy(self.store.project);first['identity']['name']='我的前锋'
        first.update(card_type='BigTime',card_series='BigTime',initial_level=20)
        first['training']['SHOOT']=5;first['custom_boosters']=[{'id':1000,'uuid':str(uuid.uuid4()),'label':'射门','conditional':False,'effects':{'20':7}}];first['booster_ids']=[0,1000]
        saved=self.store.save_player(first)
        self.assertGreaterEqual(saved['overall']['current'],saved['overall']['trained'])
        self.assertGreater(saved['overall']['trained'],saved['overall']['base'])
        second=copy.deepcopy(first);second['package_id']=str(uuid.uuid4());second['identity']['name']='我的门将';second['identity']['position']='GK';second['base_abilities']['16']=99
        self.store.save_player(second)
        self.assertEqual(self.store.list_players()['total'],2)
        self.assertEqual(self.store.list_players('门将')['total'],1)
        first['base_abilities']['20']=100;self.store.save_player(first)
        self.assertEqual(self.store.list_players()['total'],2)
        reopened=app.Store(self.store.root).saved_player(first['package_id'])['project']
        self.assertEqual(reopened['card_type'],'BigTime');self.assertEqual(reopened['training']['SHOOT'],5)
        self.assertEqual(reopened['custom_boosters'],first['custom_boosters'])
        self.assertEqual(reopened['base_abilities']['20'],100)
        self.assertEqual(self.store.saved_player(second['package_id'])['project']['identity']['position'],'GK')
        self.assertTrue(list((self.store.root/'backups').glob('saved-player-*.json')))
        with self.assertRaises(ValueError):self.store.saved_player('../current-project')

    def test_custom_coach_roundtrip_keeps_effects_identity_and_preview_separate(self):
        created=self.store.coaches.save({'name':'我的教练','effects':{'20':6,'34':2},'tactics':{'short_counter':95}})['coach']
        self.assertEqual(len(app.CATALOG['coaches']),1661)
        p=copy.deepcopy(self.store.project);p['identity']['name']='自建球员';original=copy.deepcopy(p['base_abilities'])
        p['custom_coaches']=[created];p['preview']={'coach_id':created['id']}
        p=app.normalize_project(p);result=app.calculate_overall(p,app.CATALOG)
        self.assertGreater(result['current'],result['before_coach'])
        exported=self.store.export_project(p);other=app.Store(self.root/'other');restored=other.import_project(exported['path'])
        self.assertEqual(restored['custom_coaches'][0]['uuid'],created['uuid']);self.assertEqual(restored['custom_coaches'][0]['effects'],{'20':6,'34':2})
        self.assertEqual(restored['preview']['coach_id'],created['id']);self.assertEqual(restored['base_abilities'],original)
        created['effects']['20']=8;self.store.coaches.save(created)
        self.assertEqual(app.Store(self.store.root).coaches.list()['rows'][0]['effects']['20'],8)

    def test_backup_preserves_prior_project(self):
        old=self.store.project['package_id'];p=copy.deepcopy(self.store.project);p['identity']['name']='新名字'
        self.store.save(p,manual=True)
        backups=list((self.store.root/'backups').glob('*.json'))
        self.assertTrue(any(json.loads(f.read_text(encoding='utf8'))['identity']['name']=='' for f in backups))
        self.assertEqual(self.store.project['package_id'],old)

    def test_native_art_layers_are_carried_in_project_bundle(self):
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWj8AAAAASUVORK5CYII=')
        hit=self.store.import_screenshot('data:image/png;base64,'+base64.b64encode(png).decode())
        p=copy.deepcopy(self.store.project)
        p['native_art']={'foreground':{'asset_id':hit['id'],'path':'PesMobile/Content/Original.uasset'},'full':None}
        output=self.store.export_project(p);other=app.Store(self.root/'restored')
        imported=other.import_project(output['path'])
        self.assertEqual(imported['native_art']['foreground']['path'],'PesMobile/Content/Original.uasset')
        self.assertEqual((other.root/'assets'/hit['id']).read_bytes(),png)

    def test_full_native_catalogue_contains_custom_legends(self):
        server=app.StudioServer(('127.0.0.1',0),self.store,'test-token')
        self.addCleanup(server.server_close)
        library=server.library
        self.assertEqual(library.summary()['players'],46629)
        henry=library.player('88046312750111')
        self.assertEqual(henry['name'],'Thierry Henry')
        self.assertEqual(henry['card_type'],'Epic')
        self.assertEqual(library.player('89136418985301')['name'],'Zidane')
        for pid in ('89136418985302','89136418985303'):
            player=library.player(pid);self.assertEqual(player['name'],'C. Ronaldo');self.assertIsNotNone(player['auto_model'])
        self.assertTrue(library.assets({'kind':'model','query':'43133'})['rows'])
        neuer=library.player('33185');p=copy.deepcopy(self.store.project);p['base_abilities']={k:neuer['payload']['parameters'][int(k)] for k in app.CATALOG['ABILITIES']};p['max_level']=77;p['initial_level']=61
        normalized=app.normalize_project(p);self.assertEqual(normalized['base_abilities']['14'],38);self.assertEqual(normalized['max_level'],77);self.assertEqual(normalized['initial_level'],61)

    def test_original_front_card_keeps_back_and_mobile_layers_out(self):
        library=app.NativeLibrary(app.RESOURCE,Path(__file__).absolute().parents[2]/'球员工坊-V14',self.store)
        if library.state['phase']!='ready':self.skipTest('requires the provided APK resource cache')
        modern=library.card('89138556575063');limited=library.card('370537029180759')
        self.assertEqual(len(modern['layers']),6)
        self.assertEqual(sum(r['kind']=='video' for r in modern['layers']),2)
        self.assertEqual(modern['layers'][0]['slot'],'f01')
        self.assertTrue(all(r['slot']=='portrait' or r['slot'].startswith('f') for r in modern['layers']+limited['layers']))
        self.assertTrue(any(r['name'].endswith('_lim') for r in limited['layers']))
        self.assertTrue(any(r['name']=='0501_4_f05_v' for r in limited['layers']))

    def test_retired_bigtime_models_resolve_versioned_native_faces(self):
        library=app.NativeLibrary(app.RESOURCE,Path(__file__).absolute().parents[2]/'球员工坊-V14',self.store)
        for pid,name in [('89138288266704','SK_134608ep01v0290_Face'),('89138288270047','SK_137951ep00v0294_Face')]:
            player=library.player(pid)
            self.assertEqual(next(r['name'] for r in player['models'] if r['id']==player['auto_model']),name)
            self.assertTrue(player['model_resolution']['exact'])
        legacy=library.player('89067152870864')
        self.assertTrue(legacy['auto_model']);self.assertEqual(len(legacy['face_variants']),4)
        self.assertFalse(legacy['model_resolution']['exact'])

    def test_corrupted_project_does_not_replace_current(self):
        p=copy.deepcopy(self.store.project);export=self.store.export_project(p)
        with zipfile.ZipFile(export['path']) as z:members={n:z.read(n) for n in z.namelist()}
        members['project.json']+=b' '
        broken=self.root/'bad.efproject';broken.write_bytes(app.migration.archive_bytes(members))
        before=self.store.project_path.read_bytes()
        with self.assertRaises(ValueError):self.store.import_project(broken)
        self.assertEqual(self.store.project_path.read_bytes(),before)

    def test_api_requires_session_and_rejects_cross_origin(self):
        server=app.StudioServer(('127.0.0.1',0),self.store,'test-token')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        client=http.client.HTTPConnection('127.0.0.1',server.server_port)
        self.addCleanup(client.close)
        client.request('GET','/api/bootstrap');response=client.getresponse();response.read();self.assertEqual(response.status,403)
        client.request('POST','/api/project/new',body=b'{}',headers={'X-Studio-Token':'test-token','Origin':'https://example.com','Content-Type':'application/json'})
        response=client.getresponse();response.read();self.assertEqual(response.status,403)
        client.request('GET','/api/bootstrap',headers={'X-Studio-Token':'test-token'})
        response=client.getresponse();data=json.loads(response.read());self.assertEqual(response.status,200);self.assertEqual(len(data['catalog']['ABILITIES']),26)
        client.request('GET','/%2e%2e/resources/initial-project.json',headers={'X-Studio-Token':'test-token'})
        response=client.getresponse();response.read();self.assertEqual(response.status,404)


if __name__=='__main__':unittest.main()
