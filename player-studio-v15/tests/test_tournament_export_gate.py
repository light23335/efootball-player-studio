"""Queue tournament-only exports through the real source/selection preflight."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import contextlib, copy, json, sys, tempfile, unittest, uuid, zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_package import NativePackage
from write_modes import RELEASE, source, requirements
import game_settings

CORE = Path(__file__).resolve().parents[1]

class TournamentExportGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = SimpleNamespace(root=self.root)
        self.library = SimpleNamespace(store=self.store, resources=self.root, profile={'release_id':'v17'})
        self.apk = self.root / 'original.apk'
        with zipfile.ZipFile(self.apk,'w') as z:
            z.writestr(RELEASE, json.dumps({'release_id':'v17'}))
        self.cup = {'uuid':str(uuid.uuid4()),'name':'Only Cup','enabled':True,
                    'team_ids':[1,2,3,4],'player_team_id':1,'stages':[{'type':'knockout','legs':1,'advance':1}]}
        self.world = {'stadium':{'enabled':False,'unlock_all':False},'tournaments':[self.cup]}
        (self.root / 'world-workspace.json').write_text(json.dumps(self.world),'utf8')

    def check_queue(self, writing, existing=None):
        exporter = NativePackage(self.library,CORE/'resources','unused')
        exporter.coach_candidates = lambda current: []
        exporter._booster_labels = lambda: {}
        doc, summary = source(self.apk,requirements(self.library))
        self.assertEqual(doc,{})  # No source DIY player is required either.
        body = {'apk':str(self.apk),'write_mode':writing,'write_source_token':summary['token'],
                'project':{'package_id':'unselected-empty-draft'},'selected_ids':[],
                'coach_ids':[],'pack_ids':[],'tournament_ids':[self.cup['uuid']]}
        before = copy.deepcopy(body)
        warnings=[{'team_id':1,'current_people':8,'mode':'insufficient','export_blocked':False}]
        with patch('native_package.threading.Thread') as thread, \
             (patch('write_modes.source',return_value=(existing,summary)) if existing is not None else contextlib.nullcontext()), \
             patch('native_package.load_packs',return_value=[]), \
             patch('workspace_tools.game_options',return_value={'enabled':False}), \
             patch('game_settings.settings',return_value=game_settings.normalize({})), \
             patch('world_workspace.load',return_value=self.world), \
             patch('world_workspace.selection_warnings',return_value=warnings), \
             patch('world_workspace.normalize',side_effect=lambda *args:copy.deepcopy(self.world)):
            result = exporter.start(body)
        self.assertEqual(result['phase'],'working')
        queued = thread.call_args.kwargs['args'][0]
        self.assertEqual(queued['projects'],[])
        self.assertEqual(queued['tournament_selection_warnings'],warnings)
        self.assertEqual(queued['coaches'],[])
        self.assertEqual(queued['packs'],[])
        self.assertEqual(queued['write_selected'],{'players':[],'coaches':[],'packs':[]})
        self.assertEqual({t['uuid'] for t in queued['tournament_config']},{self.cup['uuid'],*[t['uuid']for t in (existing or{}).get('tournaments',[])]})
        self.assertEqual(queued['write_mode'],'incremental' if existing else writing)
        self.assertEqual(body,before)
        thread.return_value.start.assert_called_once()

    def test_full_tournament_only_queues_without_player_or_model(self):
        self.check_queue('full')

    def test_incremental_tournament_only_queues_without_player_or_model(self):
        self.check_queue('incremental')

    def test_tournament_only_update_keeps_existing_people_packs_and_other_competitions_even_from_full_ui(self):
        other=dict(self.cup,uuid=str(uuid.uuid4()),name='Other competition')
        existing={'players':[{'identity':{'package_id':'old','card_id':7}}],'coaches':[],'packs':[],'tournaments':[other]}
        self.check_queue('full',existing)
