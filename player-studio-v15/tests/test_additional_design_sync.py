"""Saved legacy slots and workshop selections are separate sources of state."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from personal_runtime import _update_owned,sync_additional_design
from native_skill_effects import text_groups


class AdditionalDesignSyncTests(unittest.TestCase):
    def incoming(self,selected):
        return {'_personal_design_revision':'same','additional_skill_id':selected,
                '_studio_additional_design':selected,'_studio_innate_design':[40,41]}

    def test_live_report_empty_legacy_save_receives_all_ten_even_at_same_revision(self):
        selected=[1,2,3,7,17,19,23,38,55,44]
        current={'_personal_design_revision':'same','additional_skill_id':[],
                 'gameplayer_id':{'id':12345,'serial':901234},
                 'level_info':{'level':35,'exp_total':98765,'customize_point':6},
                 'games':143,'goal':98,'is_lock':'YES','unknown_future':{'keep':True}}
        before=copy.deepcopy(current)
        out=_update_owned(current,{'owned':self.incoming(selected)},{},[])
        self.assertEqual(out['additional_skill_id'],selected)
        self.assertEqual(out['_studio_additional_design'],selected)
        for key in before:
            if key!='additional_skill_id':self.assertEqual(out[key],before[key],key)
        self.assertEqual(current,before)
        self.assertEqual(_update_owned(out,{'owned':self.incoming(selected)},{},[]),out)

    def test_legacy_empty_placeholder_slots_are_repaired(self):
        out=sync_additional_design({'additional_skill_id':[74]*5},self.incoming(list(range(10))))
        self.assertEqual(out['additional_skill_id'],list(range(10)))

    def test_later_game_learning_and_removal_survive_unrelated_design_changes(self):
        current=sync_additional_design({'additional_skill_id':[]},self.incoming([1,2]))
        current['additional_skill_id']=[1,3]  # Game removed 2 and learned 3.
        newer=self.incoming([1,2]);newer['name']='Edited card art'
        self.assertEqual(sync_additional_design(current,newer),current)

    def test_configuration_edit_replaces_its_own_slots_and_retains_learned_skills(self):
        current={'additional_skill_id':[1,2,3], '_studio_additional_design':[1,2]}
        out=sync_additional_design(current,self.incoming([4,5]))
        self.assertEqual(out['additional_skill_id'],[4,5,3])
        self.assertEqual(sync_additional_design(out,self.incoming([]))['additional_skill_id'],[3])

    def test_full_selection_retains_displaced_learned_values_for_later_free_slots(self):
        current={'additional_skill_id':[33,34]}
        out=sync_additional_design(current,self.incoming(list(range(10))))
        self.assertEqual(out['additional_skill_id'],list(range(10)))
        self.assertEqual(out['_studio_additional_retained'],[33,34])
        out=sync_additional_design(out,self.incoming([15]))
        self.assertEqual(out['additional_skill_id'],[15,33,34])
        self.assertEqual(out['_studio_additional_retained'],[])

    def test_old_export_without_tracking_metadata_is_supported(self):
        out=sync_additional_design({'additional_skill_id':[]},{'additional_skill_id':[2,75,78]})
        self.assertEqual(out['additional_skill_id'],[2,75,78])

    def test_legacy_game_learned_skills_without_config_are_preserved(self):
        current={'additional_skill_id':[7,15,44]}
        self.assertEqual(sync_additional_design(current,self.incoming([]))['additional_skill_id'],[7,15,44])

    def test_zidane_turn_native_message_gets_real_text_in_all_export_locales(self):
        metadata=json.loads((Path(__file__).resolve().parents[1]/'resources/native-skill-ui.json').read_text('utf8'))
        row=next(r for r in metadata['rows'] if r['id']==9)
        self.assertEqual(row['name_msg'],(352<<16)|145)
        for locale in ('zha','chi','eng'):
            texts={(g['id']<<16)|k:v for g in text_groups(locale=locale) for k,v in g['items'].items()}
            self.assertEqual(texts[row['name_msg']], 'Zidane Turn' if locale=='eng' else '施丹式转身')
            self.assertNotIn('dummy',texts[row['description_msg']].lower())


if __name__=='__main__':unittest.main()
