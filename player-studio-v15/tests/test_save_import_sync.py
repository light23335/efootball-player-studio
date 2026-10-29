from pathlib import Path
import sys,types,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from personal_runtime import install_save_import_sync

class SaveImportSyncTests(unittest.TestCase):
    def test_sync_runs_after_restore_before_caller_reopens_and_preserves_return(self):
        events=[];module=types.ModuleType('save_transfer')
        def original(*a,**kw):events.append('restore');return {'restored':True}
        module.restore_snapshot=original
        doc={'coaches':[{'uuid':'coach'}]}
        with patch.dict(sys.modules,{'save_transfer':module}),patch('personal_runtime.apply_definitions',side_effect=lambda c,d:events.append('players')) as players,patch('personal_runtime.apply_coaches',side_effect=lambda c,d:events.append('coaches')):
            install_save_import_sync(lambda:doc)
            wrapper=module.restore_snapshot
            install_save_import_sync(lambda:doc)
            self.assertIs(wrapper,module.restore_snapshot)
            result=module.restore_snapshot(snapshot='unused',destination=':memory:',user_version=1)
            events.append('reopen')
            self.assertEqual(events,['restore','players','coaches','reopen'])
            self.assertEqual(result,{'restored':True})
            self.assertIs(players.call_args.args[1],doc)

    def test_failed_restore_does_not_apply_and_sync_failure_reaches_import_recovery(self):
        module=types.ModuleType('save_transfer')
        module.restore_snapshot=lambda *a,**kw:(_ for _ in ()).throw(ValueError('invalid save'))
        with patch.dict(sys.modules,{'save_transfer':module}),patch('personal_runtime.apply_definitions') as apply:
            install_save_import_sync(lambda:{})
            with self.assertRaisesRegex(ValueError,'invalid save'):module.restore_snapshot('a',':memory:')
            apply.assert_not_called()
        module.restore_snapshot=lambda *a,**kw:None
        with patch.dict(sys.modules,{'save_transfer':module}),patch('personal_runtime.apply_definitions',side_effect=ValueError('collision')):
            install_save_import_sync(lambda:{})
            with self.assertRaisesRegex(ValueError,'collision'):module.restore_snapshot('a',':memory:')

if __name__=='__main__':unittest.main()
