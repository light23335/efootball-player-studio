"""Native original-League availability must survive exports with no custom cups."""
import io,json,unittest
from pathlib import Path
from native_package import competition_menu_hooks

ROOT=Path(__file__).resolve().parents[2]
RESOURCES=ROOT/'player-studio-v15/resources'
ENGINE=ROOT/'.work/xi-v17-gameplay-compare/v17-engine.so'

class CompetitionMenuExportTests(unittest.TestCase):
    def test_original_league_bridge_is_compiled_without_any_custom_tournaments(self):
        p=json.loads((RESOURCES/'tournament_schedule_ui/native-home.json').read_text('utf8'))
        result=competition_menu_hooks(io.BytesIO(ENGINE.read_bytes()),RESOURCES,p['menu_source_sha256'],[])
        self.assertEqual([h['name']for h in result],['tournament-native-home-v1'])
        home=result[0];entry=next(r for r in home['extra_entries']if r['name']=='original_league_native_availability')
        self.assertEqual(entry['address'],0x74a4ad0)
        self.assertEqual(home['tournament_home_channel'],p['tournament_home_channel'])
        self.assertEqual(home['special_plan_team_identity']['rental_field_encoding'],'native-team-id-shift-left-14')
        self.assertEqual(home['special_plan_team_identity']['native_setter'],0x7a81db4)

    def test_selected_tournament_keeps_schedule_and_contract_bridges_as_well(self):
        p=json.loads((RESOURCES/'tournament_schedule_ui/native-home.json').read_text('utf8'))
        result=competition_menu_hooks(io.BytesIO(ENGINE.read_bytes()),RESOURCES,p['menu_source_sha256'],[{'event_id':190000001}])
        self.assertEqual(len(result),3)
        self.assertEqual(sum(h['name']=='tournament-native-home-v1'for h in result),1)
        contract=json.loads((RESOURCES/'tournament_schedule_ui/native-contract.json').read_text('utf8'))
        emitted=next(h for h in result if h['name']==contract['name'])
        self.assertEqual(emitted['body_sha256'],contract['body_sha256'])

if __name__=='__main__':unittest.main()
