"""Old designs may exceed game display limits without losing editor data."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from native_player import compile_player
from project_sharing import export_selected


class SkillProjectCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = app.Store(self.root/'data')
        self.skills = [int(k) for k in app.CATALOG['PARAMETER_BY_SKILL']
                       if '预留' not in app.CATALOG['SKILL_LABELS'].get(str(k), '')]
        self.project = app.default_project()
        self.project['identity']['name'] = '旧版超容量工程'
        self.project['innate_skills'] = self.skills[:31]
        self.project['additional_skills'] = self.skills[31:46]

    def assertSkills(self, project):
        self.assertEqual(project['innate_skills'], self.project['innate_skills'])
        self.assertEqual(project['additional_skills'], self.project['additional_skills'])

    def test_old_autosave_opens_without_reset_or_unreadable_backup(self):
        self.store.project_path.write_text(json.dumps(self.project), encoding='utf8')
        reopened = app.Store(self.store.root)
        self.assertSkills(reopened.project)
        self.assertEqual(reopened.project['package_id'], self.project['package_id'])
        self.assertFalse(list((self.store.root/'backups').glob('unreadable-*.json')))

    def test_old_saved_file_is_listed_without_rewriting_original(self):
        path = self.store._player_path(self.project['package_id'])
        entry = {'format': '73efootball-saved-player', 'version': 1,
                 'saved_at': '2026-10-01', 'project': self.project}
        path.write_text(json.dumps(entry), encoding='utf8')
        before = path.read_bytes()
        listed = self.store.list_players()
        self.assertEqual(listed['saved_total'], 1)
        self.assertEqual(listed['errors'], [])
        self.assertSkills(self.store.saved_player(path.stem)['project'])
        self.assertEqual(path.read_bytes(), before)

    def test_save_and_reopen_keep_all_skills_and_categories(self):
        self.store.save_player(self.project)
        self.store.save(self.project, manual=True)
        reopened = app.Store(self.store.root)
        self.assertSkills(reopened.project)
        self.assertSkills(reopened.saved_player(self.project['package_id'])['project'])

    def test_single_player_export_and_import_keep_all_skills(self):
        exported = self.store.export_project(self.project)
        other = app.Store(self.root/'imported')
        self.assertSkills(other.import_project(exported['path']))

    def test_shared_project_export_and_import_keep_all_skills(self):
        self.store.save_player(self.project)
        exported = export_selected(self.store, [self.project['package_id']], self.project)
        other = app.Store(self.root/'shared')
        imported = other.import_project(exported['path'])
        self.assertSkills(imported)
        self.assertSkills(other.saved_player(imported['package_id'])['project'])

    def test_invalid_skill_id_still_reports_real_reason_and_preserves_file(self):
        self.store.save_player(self.project)
        invalid = copy.deepcopy(self.project)
        invalid['package_id'] = 'f64c7ce3-bfe9-4d99-92ec-06952636dfb4'
        invalid['innate_skills'].append(9999)
        path = self.store._player_path(invalid['package_id'])
        path.write_text(json.dumps({'format': '73efootball-saved-player', 'version': 1,
                                    'saved_at': '2026-10-01', 'project': invalid}), encoding='utf8')
        before = path.read_bytes()
        result = self.store.list_players()
        self.assertEqual(result['saved_total'], 1)
        self.assertEqual(len(result['errors']), 1)
        self.assertIn('未适配的技能编号', result['errors'][0]['message'])
        self.assertEqual(path.read_bytes(), before)

    def test_game_compiler_retains_capacity_guard_without_mutating_design(self):
        for innate, additional, expected in [(101, 0, '100'), (20, 101, '100')]:
            with self.subTest(innate=innate, additional=additional):
                project = copy.deepcopy(self.project)
                # Isolate the native capacity guard from catalogue validation.
                project['innate_skills'] = [self.skills[0]]*innate
                project['additional_skills'] = [self.skills[-1]]*additional
                before = copy.deepcopy(project)
                with self.assertRaisesRegex(ValueError, '工程已完整保留.*'+expected):
                    compile_player(project, None, None, None, None, None, None)
                self.assertEqual(project, before)


if __name__ == '__main__':
    unittest.main()
