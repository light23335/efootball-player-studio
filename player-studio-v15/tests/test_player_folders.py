from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import copy,json,sys,tempfile,unittest,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app


class PlayerFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=app.Store(self.temp.name);self.folders=self.store.player_folders;self.ids=[]
        for label in ('Salah','Firmino','Mane'):
            p=app.default_project();p['identity']['name']=label;self.store.save_player(p);self.ids.append(p['package_id'])
        self.original={p.name:p.read_bytes()for p in (self.store.root/'players').glob('*.json')}

    def assertPlayersUntouched(self):
        self.assertEqual({p.name:p.read_bytes()for p in (self.store.root/'players').glob('*.json')},self.original)

    def test_create_can_select_players_and_existing_folder_can_add_more_after_restart(self):
        result=self.folders.create('利物浦',[self.ids[0]])
        folder=result['folder']['id'];self.assertEqual(result['rows'][0]['count'],1)
        reopened=app.Store(self.temp.name)
        result=reopened.player_folders.add(folder,self.ids[1:])
        self.assertEqual(result['rows'][0]['count'],3);self.assertEqual(result['unfiled_count'],0)
        self.assertEqual(reopened.list_players(folder_id=folder)['total'],3)
        self.assertEqual(reopened.list_players('Mane',folder_id=folder)['rows'][0]['name'],'Mane')
        self.assertPlayersUntouched()

    def test_create_empty_then_batch_add_is_idempotent(self):
        folder=self.folders.create('稍后整理')['folder']['id']
        self.assertEqual(self.store.list_players(folder_id=folder)['total'],0)
        self.assertEqual(self.folders.add(folder,[self.ids[0],self.ids[0]])['added'],1)
        self.assertEqual(self.folders.add(folder,[self.ids[0]])['added'],0)
        self.assertEqual(self.store.list_players()['total'],3);self.assertPlayersUntouched()

    def test_move_changes_only_classification_and_remove_returns_to_unfiled(self):
        a=self.folders.create('A',self.ids[:2])['folder']['id'];b=self.folders.create('B')['folder']['id']
        self.folders.add(b,[self.ids[0]])
        self.assertEqual(self.store.list_players(folder_id=a)['total'],1)
        self.assertEqual(self.store.list_players(folder_id=b)['total'],1)
        self.folders.remove(a,[self.ids[0]])  # Stale removal cannot detach a player already moved elsewhere.
        self.assertEqual(self.store.list_players(folder_id=b)['total'],1)
        self.folders.remove(b,[self.ids[0]])
        self.assertEqual(self.store.list_players(folder_id='unfiled')['total'],2);self.assertPlayersUntouched()

    def test_delete_requires_confirmation_keeps_all_players_and_rename_keeps_members(self):
        folder=self.folders.create('Old',self.ids)['folder']['id']
        self.folders.rename(folder,'New')
        self.assertTrue(all(r['folder_name']=='New'for r in self.store.list_players()['rows']))
        with self.assertRaises(ValueError):self.folders.delete(folder)
        self.folders.delete(folder,True)
        self.assertEqual(self.store.list_players(folder_id='unfiled')['total'],3);self.assertPlayersUntouched()

    def test_invalid_names_ids_and_missing_players_never_partially_change_members(self):
        folder=self.folders.create('One',self.ids[:1])['folder']['id'];before=self.folders.path.read_bytes()
        for bad in ('',' ', 'x'*61,'a\nb'):
            with self.assertRaises(ValueError):self.folders.create(bad)
        with self.assertRaises(ValueError):self.folders.create('oNE')
        for players in ([self.ids[1],str(uuid.uuid4())],['../current-project'],None):
            with self.assertRaises(ValueError):self.folders.add(folder,players)
        with self.assertRaises(ValueError):self.folders.add('../outside',[self.ids[0]])
        self.assertEqual(self.folders.path.read_bytes(),before);self.assertPlayersUntouched()

    def test_corrupt_index_preserves_original_and_all_players_remain_readable(self):
        raw=b'["bad index"]';self.folders.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'原文件已保留'):self.folders.listing()
        with self.assertRaises(ValueError):self.folders.create('One')
        result=self.store.list_players()
        self.assertEqual(result['total'],3);self.assertIn('原文件已保留',result['folder_error'])
        self.assertEqual(self.folders.path.read_bytes(),raw);self.assertPlayersUntouched()

    def test_atomic_write_failure_keeps_previous_index_and_players(self):
        folder=self.folders.create('One',self.ids[:1])['folder']['id'];before=self.folders.path.read_bytes()
        with patch('player_folders.os.replace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.folders.add(folder,self.ids[1:])
        self.assertEqual(self.folders.path.read_bytes(),before)
        self.assertFalse(list(self.store.root.glob('.player-folders-*.tmp')));self.assertPlayersUntouched()

    def test_parallel_additions_do_not_lose_members(self):
        folder=self.folders.create('One')['folder']['id']
        with ThreadPoolExecutor(max_workers=3)as pool:
            results=list(pool.map(lambda ident:self.folders.add(folder,[ident]),self.ids))
        self.assertEqual(self.folders.listing()['rows'][0]['count'],3);self.assertPlayersUntouched()

    def test_player_deletion_cleans_membership_and_empty_folder_survives(self):
        folder=self.folders.create('Keep folder',self.ids[:1])['folder']['id']
        self.store.delete_player(self.ids[0],True)
        self.assertNotIn(self.ids[0],self.folders.read()['members'])
        self.assertEqual(self.folders.listing()['rows'][0]['count'],0)
        self.folders.add(folder,[self.ids[1]])
        self.assertEqual(self.folders.listing()['rows'][0]['count'],1)

    def test_empty_existing_folder_supports_search_and_pagination(self):
        folder=self.folders.create('Two',self.ids[:2])['folder']['id']
        self.assertEqual(len(self.store.list_players(offset=0,limit=1,folder_id=folder)['rows']),1)
        self.assertEqual(len(self.store.list_players(offset=1,limit=1,folder_id=folder)['rows']),1)
        self.assertEqual(self.store.list_players('not found',folder_id=folder)['total'],0)
        with self.assertRaises(ValueError):self.store.list_players(folder_id=str(uuid.uuid4()))
