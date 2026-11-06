"""The native off-position exception cannot escape its tournament entry."""
import copy,json,struct,tempfile,unittest
from pathlib import Path
from ai_match_runtime import Bridge
from test_ai_match_manager import fixture
from test_tournament_fallback_coaching import POLICY

LAYOUT=json.loads((Path(__file__).resolve().parents[1]/'resources/native-ai-match-adapter.json').read_text('utf8'))['channel_schema']
RULES={**dict.fromkeys(('two_leg','first_leg','second_leg','extra_time','penalties','away_goals','away_goals_extra_time'),False),'prior_goals':[0,0]}

class TournamentFallbackRuntimeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.spec,_=fixture();self.spec['entry_id']='fallback-scope'
  self.bridge=Bridge(bytearray(32768),0,LAYOUT,lambda:None)

 def test_requires_a_real_tournament_contract_and_supported_adapter(self):
  self.spec['tournament_fallback']=copy.deepcopy(POLICY)
  with self.assertRaisesRegex(ValueError,'scoped native tournament'):self.bridge.configure(self.spec,self.root)
  self.spec['tournament_rules']=copy.deepcopy(RULES)
  old={k:v for k,v in LAYOUT.items()if k!='tournament_relaxed_aptitude'}
  bridge=Bridge(bytearray(32768),0,old,lambda:None)
  with self.assertRaisesRegex(ValueError,'scoped native tournament'):bridge.configure(self.spec,self.root)

 def test_reconfiguration_explicitly_clears_the_exception_for_ordinary_ai(self):
  self.spec.update(tournament_fallback=copy.deepcopy(POLICY),tournament_rules=copy.deepcopy(RULES))
  self.bridge.configure(self.spec,self.root)
  value=lambda name:struct.unpack('<I',self.bridge.read(LAYOUT[name],4))[0]
  self.assertEqual(value('tournament_relaxed_aptitude'),0x54584631);self.assertEqual(value('rules_enabled'),1)
  ordinary=copy.deepcopy(self.spec);ordinary.pop('tournament_fallback');ordinary.pop('tournament_rules')
  ordinary['entry_id']='ordinary-ai'
  self.bridge.configure(ordinary,self.root)
  self.assertEqual(value('tournament_relaxed_aptitude'),0);self.assertEqual(value('rules_enabled'),0)

 def test_invalid_exception_cannot_silently_become_an_enabled_native_flag(self):
  self.spec.update(tournament_fallback={**POLICY,'original_person_count':10},tournament_rules=copy.deepcopy(RULES))
  with self.assertRaisesRegex(ValueError,'Invalid tournament fallback'):self.bridge.configure(self.spec,self.root)
  self.assertEqual(self.bridge.read(LAYOUT['enabled'],4),bytes(4))

if __name__=='__main__':unittest.main()
