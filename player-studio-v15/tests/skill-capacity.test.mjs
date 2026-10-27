import test from 'node:test';
import assert from 'node:assert/strict';
import {skillCapacityNotice} from '../web/skill-capacity.js';

test('projects within game display capacity have no overflow warning', () => {
  assert.equal(skillCapacityNotice({}), '');
  assert.equal(skillCapacityNotice({innate_skills: Array(100), additional_skills: Array(100)}), '');
  assert.equal(skillCapacityNotice({innate_skills: Array(31), additional_skills: Array(15)}), '');
});

test('either category beyond capacity explains preservation and installation limits', () => {
  for (const [innate, additional] of [[101, 0], [0, 101], [102, 105]]) {
    const project = {innate_skills: Array.from({length: innate}, (_, i) => i), additional_skills: Array.from({length: additional}, (_, i) => 40+i)};
    const before = structuredClone(project);
    const notice = skillCapacityNotice(project);
    assert.match(notice, new RegExp(`天生 ${innate} 项、追加 ${additional} 项`));
    assert.match(notice, /已完整保留/);
    assert.match(notice, /编辑、保存和分享工程/);
    assert.match(notice, /生成 APK 前请调整数量/);
    assert.deepEqual(project, before);
  }
});
