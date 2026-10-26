"""A valid exported V17 identity must remain valid as the next APK input."""
from pathlib import Path
import copy,sys,unittest,uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_player import reserve_identity
from personal_source import ownership,seed


class PersonalSourceIdentityTests(unittest.TestCase):
    def project(self,bound=None):
        return {'package_id':str(uuid.uuid4()),
                'identity':{'bind_original_player':bound is not None,'original_player_id':str(bound) if bound else None},
                'native_card':{'native_style':'0501','native_agent':123}}

    def document(self,identity):
        return {'players':[{'identity':identity,'base_parameters':[0]*147}],
                'native_binding':{'routes':[{'cardId':identity['card_id'],'portraitKey':'8000001'}]}}

    def test_newly_allocated_identity_reseeds_unchanged(self):
        project=self.project();registry={}
        identity=reserve_identity(project,set(),registry)
        before=copy.deepcopy(identity);assets={}
        owners=seed(self.document(identity),registry,assets)
        self.assertEqual(identity,before)
        self.assertEqual(registry[project['package_id']]['person_id'],identity['person_id'])
        self.assertIn(identity['person_id'],owners[project['package_id']]['aliases'])
        self.assertEqual(reserve_identity(project,set(),registry),identity)

    def test_legacy_unbound_namespace_boundaries_remain_valid(self):
        for person in (90000000,95012443,96988091,98999999):
            with self.subTest(person=person):
                card=(0x51<<40)|(123<<28)|person
                identity={'package_id':str(uuid.uuid4()),'person_id':person,'card_id':card,'previous_card_ids':[card]}
                self.assertIn(person,ownership(self.document(identity))[identity['package_id']]['aliases'])

    def test_bound_unbound_and_rebound_history_preserves_full_person_key(self):
        # Real V17 card layout: low 28 bits can include native person flags.
        original=(0x51<<40)|(278<<28)|0x0500dfd8
        project=self.project(original);registry={};assets={};occupied={original}
        for bind in (True,False,True):
            with self.subTest(bind=bind):
                project['identity']['bind_original_player']=bind
                identity=reserve_identity(project,occupied,registry)
                owners=seed(self.document(identity),registry,assets)
                self.assertNotIn(original,owners[project['package_id']]['aliases'])
                if bind:self.assertNotIn(original&0xfffffff,owners[project['package_id']]['aliases'])
                self.assertEqual(identity['card_id']&0xfffffff,identity['person_id'])

    def test_foreign_or_out_of_range_identities_remain_rejected(self):
        identity=reserve_identity(self.project(),set(),{})
        for person in (239999,248091,260000,89999999,99000000):
            with self.subTest(person=person):
                invalid=copy.deepcopy(identity)
                invalid.update(person_id=person,independent_person_id=person)
                with self.assertRaisesRegex(ValueError,'专用范围'):ownership(self.document(invalid))

    def test_foreign_history_and_artwork_are_not_claimed(self):
        identity=reserve_identity(self.project(),set(),{})
        invalid=copy.deepcopy(identity);invalid['previous_card_ids'].append((0x51<<40)|7511)
        with self.assertRaisesRegex(ValueError,'专用范围'):ownership(self.document(invalid))
        document=self.document(identity);document['native_binding']['routes'][0]['portraitKey']='7511'
        with self.assertRaisesRegex(ValueError,'专用范围'):ownership(document)


if __name__=='__main__':unittest.main()
