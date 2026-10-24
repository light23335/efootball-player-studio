from pathlib import Path
import copy,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_models import person_keys,resolve_face
from native_player import reserve_identity


class NativePersonKeyTests(unittest.TestCase):
    def test_bt_and_highlight_flags_resolve_the_original_face_family(self):
        self.assertIn('57304',person_keys(89137029898200))
        self.assertIn('105029',person_keys(106734786026053))
        rows=[{'name':'SK_57304_Face'},{'name':'SK_57304ep01v0285_Face'}]
        selected,info=resolve_face(rows,89137029898200)
        self.assertEqual(selected['name'],'SK_57304ep01v0285_Face')
        self.assertTrue(info['exact'])

    def test_existing_private_identity_keeps_card_and_progress_keys(self):
        uid='cb3fc821-49e9-4dab-9c62-9e1eab047cb8'
        project={'package_id':uid,'native_card':{'native_style':'0501','native_agent':373,'source_id':'52777095109189'}}
        registry={uid:{'person_id':98317425,'card_ids':[]}}
        before=copy.deepcopy(registry);identity=reserve_identity(project,set(),registry)
        self.assertEqual(identity['person_id'],before[uid]['person_id'])
        self.assertEqual(identity['card_id']&0xfffffff,98317425)
        self.assertEqual(person_keys(identity['person_id']),['98317425','14431345','6042737','1848433'])
        occupied={1848433};second={'package_id':'b202c510-0485-418a-863d-79247e9044aa','native_card':project['native_card']}
        created=reserve_identity(second,occupied,registry)
        self.assertFalse(set(map(int,person_keys(created['person_id'])))&occupied)


if __name__=='__main__':unittest.main()
