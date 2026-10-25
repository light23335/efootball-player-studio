"""Extended editor ownership -> real client row -> import/share round trips."""
from pathlib import Path
import copy,json,sqlite3,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from custom_skills import (REVISION,ROWS,SOURCE_BIT,COUNT,enabled,extend_catalog,
                           source_fields,require_catalog)
from native_player import compile_player
from native_tables import player_record
from native_skill_effects import decode_skills,required,text_groups


class CustomSkillDataTests(unittest.TestCase):
    def test_owned_legacy_additional_ids_migrate_even_when_design_revision_matches(self):
        from personal_runtime import _update_owned
        for values,expected in (([2,74,76],[2,75,77]),([2,75,77],[2,75,77])):
            current={'_personal_design_revision':'same','additional_skill_id':values,'earned_xp':98765}
            definition={'owned':{'_personal_design_revision':'same','additional_skill_id':[2,75,77],
                                '_studio_custom_skill_protocol':REVISION}}
            updated=_update_owned(current,definition,{},[])
            self.assertEqual(updated['additional_skill_id'],expected)
            self.assertEqual(updated['earned_xp'],98765)
            self.assertEqual(current['additional_skill_id'],values)
            self.assertEqual(_update_owned(updated,definition,{},[]),updated)
    def test_old_diy_additional_ids_upgrade_once_and_projects_stay_unchanged(self):
        from custom_skills import upgrade_definitions
        players=[{'studio_custom_skills':[74,75,76,77],'owned':{'additional_skill_id':[25,74,75,76,77]}}]
        upgrade_definitions(players)
        self.assertEqual(players[0]['owned']['additional_skill_id'],[25,75,76,77,78])
        upgrade_definitions(players)
        self.assertEqual(players[0]['owned']['additional_skill_id'],[25,75,76,77,78])
        self.assertEqual(players[0]['studio_custom_skills'],[74,75,76,77])
    @classmethod
    def setUpClass(cls):
        cls.catalog=copy.deepcopy(app.CATALOG)
        extend_catalog(cls.catalog)
        with sqlite3.connect(app.RESOURCE/'library.sqlite3') as db:
            cls.source=json.loads(db.execute('select payload from players where id="7511"').fetchone()[0])
        cls.costs=json.loads((app.RESOURCE/'native-progression.json').read_text(encoding='utf8'))['costs']
        cls.fields=json.loads((app.RESOURCE/'native-player-fields.json').read_text(encoding='utf8'))
        cls.abilities=json.loads((app.RESOURCE/'native-ability-bits.json').read_text(encoding='utf8'))
        cls.skills=json.loads((app.RESOURCE/'native-skill-bits.json').read_text(encoding='utf8'))
        cls.skills.update(source_fields())

    def project(self,custom=True):
        p=app.default_project();p['identity']['name']='Skill protocol test'
        p['innate_skills']=[25]+([74,75] if custom else [])
        p['additional_skills']=[76,77] if custom else []
        return p

    def compile(self,p,catalog=None):
        identity={'card_id':90000001,'person_id':90000001,'package_id':p['package_id'],'previous_card_ids':[]}
        template=bytes.fromhex(self.source['_studio_client_record'])
        definition=compile_player(p,catalog or self.catalog,self.costs,identity,self.source,18,103,template)
        record=player_record(template,p,definition,self.fields,self.abilities,self.skills)
        return definition,record

    def test_catalogue_exposure_requires_an_explicit_released_matching_runtime(self):
        runtime=json.loads((app.RESOURCE/'native-skill-effects.json').read_text(encoding='utf8'))
        self.assertEqual(enabled(app.RESOURCE),runtime.get('production_ready') is True
                         and runtime.get('custom_skill_protocol')==REVISION)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'native-skill-effects.json'
            for ready,protocol,wanted in ((False,REVISION,False),(True,'wrong',False),(True,REVISION,True)):
                path.write_text(json.dumps({'production_ready':ready,'custom_skill_protocol':protocol}),encoding='utf8')
                self.assertEqual(enabled(tmp),wanted)
        p=self.project()
        raw_catalog=json.loads((app.RESOURCE/'catalog.json').read_text(encoding='utf8'))
        with self.assertRaisesRegex(ValueError,'尚未发布'):require_catalog(p,raw_catalog)

    def test_compiler_keeps_all_owned_arrays_at_147_and_writes_independent_client_markers(self):
        p=self.project();definition,record=self.compile(p)
        baseline=copy.deepcopy(p);baseline['innate_skills']=[25];baseline['additional_skills']=[]
        before,before_row=self.compile(baseline)
        for key in ('base_parameters',):
            self.assertEqual(len(definition[key]),147)
            self.assertEqual(definition[key],before[key])
        for key in ('parameters','_careerplan_base_parameters'):
            self.assertEqual(len(definition['owned'][key]),147)
        self.assertEqual(len(definition['maximum_development']['parameters']),147)
        self.assertEqual(definition['owned']['additional_skill_id'],[77,78])
        self.assertEqual(definition['studio_custom_skills'],[74,75,76,77])
        self.assertTrue(required([definition],self.catalog))
        self.assertEqual(int.from_bytes(record,'little')^int.from_bytes(before_row,'little'),
                         ((1<<COUNT)-1)<<SOURCE_BIT)

    def test_client_row_decode_and_clear_never_grow_or_overwrite_owned_parameters(self):
        p=self.project();definition,record=self.compile(p)
        decoded=[0]*147
        selected=decode_skills(int.from_bytes(record,'little'),decoded,self.catalog,self.skills)
        self.assertTrue({25,74,75,76,77}<=set(selected))
        self.assertEqual(len(decoded),147)
        self.assertEqual(decoded[self.catalog['PARAMETER_BY_SKILL']['25']],1)
        p['innate_skills']=[25];p['additional_skills']=[]
        cleared=player_record(record,p,definition,self.fields,self.abilities,self.skills)
        selected=decode_skills(int.from_bytes(cleared,'little'),[0]*147,self.catalog,self.skills)
        self.assertFalse(set(range(74,78))&set(selected))

    def test_project_share_preserves_the_users_innate_and_additional_selections(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'CATALOG',self.catalog):
            first=app.Store(Path(tmp)/'first');second=app.Store(Path(tmp)/'second')
            p=self.project()
            restored=second.import_project(first.export_project(p)['path'])
            self.assertEqual(restored['innate_skills'],[25,74,75])
            self.assertEqual(restored['additional_skills'],[76,77])
            self.assertEqual(restored['package_id'],p['package_id'])

    def test_new_names_and_descriptions_merge_with_existing_native_text_groups(self):
        original=text_groups()
        with patch('custom_skills.enabled',return_value=True):actual=text_groups()
        by_id={row['id']:row for row in actual}
        self.assertEqual(len(by_id),len(actual))
        for row in original:
            for key,value in row['items'].items():self.assertEqual(by_id[row['id']]['items'][key],value)
        self.assertEqual([by_id[352]['items'][60000+i] for i in range(4)],[r['name'] for r in ROWS])
        self.assertEqual([by_id[353]['items'][60000+i] for i in range(4)],[r['description'] for r in ROWS])


if __name__=='__main__':unittest.main()
