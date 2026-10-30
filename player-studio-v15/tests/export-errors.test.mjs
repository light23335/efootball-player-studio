import test from 'node:test';
import assert from 'node:assert/strict';
import {exportStep} from '../web/export-errors.js';
test('client-only PNG and GLB failures retain player, action and root cause',async()=>{
  const cause=new Error('Texture could not be loaded');
  await assert.rejects(exportStep('Salah','导出 GLB',()=>{throw cause;}),error=>error.message.includes('Salah')&&error.message.includes('导出 GLB')&&error.cause===cause);
});
test('API export diagnostics are preserved without repeated prefixes',async()=>{
  const cause=new Error('导出失败：球员「One」／读取纹理。原因：missing');
  await assert.rejects(exportStep('One','导出 PNG',()=>{throw cause;}),error=>error===cause);
});
