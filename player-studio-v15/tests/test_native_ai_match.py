import copy
import ctypes
import hashlib
import io
import json
import struct
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from native_ai_match import hooks
from native_package import hook_archive,bytecode
from personal_binding import compose,relocate_code,_BindingCtypes

ROOT=Path(__file__).resolve().parents[1];RESOURCE=ROOT/'resources'


class Engine:
    def __init__(self,data):
        self.rows={r['file_offset']:bytes.fromhex(r['expected_hex'])for r in [data,*data['extra_entries'],*data['native_import_probes']]}
        self.at=0
    def seek(self,at):self.at=at
    def read(self,n):return self.rows.get(self.at,bytes(n))[:n]


class NativeMatchTests(unittest.TestCase):
    def bundle(self):
        return json.loads((RESOURCE/'native-ai-match-adapter.json').read_text('utf8'))

    def test_resource_is_current_and_execution_has_reviewed_local_evidence(self):
        data=self.bundle()
        self.assertEqual(data['source_sha256'],hashlib.sha256((ROOT/'maintenance/ai_match_native.c').read_bytes()).hexdigest())
        self.assertTrue(data['observer_ready']);self.assertTrue(data['automatic_execution_verified'])
        self.assertTrue(all(data['execution_proof'].values()))
        self.assertTrue(data['validation']['local_only'])
        for name,digest in data['validation']['source_sha256'].items():
            self.assertEqual(digest,hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),name)
        self.assertEqual(len(hooks(Engine(data),RESOURCE)),1)
        bad=Engine(data);bad.rows[data['extra_entries'][0]['file_offset']]=bytes(64)
        with self.assertRaisesRegex(ValueError,'关闭'):hooks(bad,RESOURCE)

    def compose(self,split=False):
        original=json.loads((RESOURCE/'native-binding-profile.json').read_text())
        profile=json.loads((RESOURCE/'native-route-templates.json').read_text())
        profile['external_routes']=split
        profile['native_hooks']=hooks(Engine(self.bundle()),RESOURCE)
        return original,compose(original,[],profile)

    def test_split_relocation_keeps_channel_state_and_fence_in_correct_regions(self):
        original,payload=self.compose(True);descriptor=payload['ai_match_channel']
        self.assertEqual(descriptor['code_region'],'extension')
        self.assertEqual(descriptor['data_offset']%16,0)
        code=bytearray.fromhex(payload['blob_hex'])
        struct.pack_into('<Q',code,payload['back_fixup'],0x7000000000+payload['hooks'][0]['address']+4)
        prefix,extension=relocate_code(payload,bytes(code),0x7100000000,0x7300000538,0x7500000000,0x7600000000)
        fence=descriptor['fence_offset']
        self.assertEqual(extension[fence:fence+8],bytes.fromhex('bf3b03d5c0035fd6'))
        self.assertIn(0x7600000000+descriptor['data_offset'],
                      [struct.unpack_from('<Q',extension,at)[0] for at,_ in payload['extension_writable_pointer_fixups']])
        self.assertEqual(prefix[:original['back_fixup']],bytes(code)[:original['back_fixup']])
        self.assertLessEqual(len(prefix),4096)

    def test_registration_resolves_relocated_fence_without_calling_engine_from_worker(self):
        _,payload=self.compose(True);descriptor=payload['ai_match_channel']
        binding=_BindingCtypes(ctypes,payload)
        with patch('ai_match_runtime.register_channel',return_value='registered') as register:
            binding._register_channel(0x7100000000,0x7300000538)
        self.assertEqual(binding.channel,'registered')
        self.assertIs(register.call_args.args[0],binding.writable)
        self.assertEqual(register.call_args.args[1],descriptor['data_offset'])
        fence=register.call_args.args[3]
        self.assertEqual(ctypes.cast(fence,ctypes.c_void_p).value,0x7300000538+descriptor['fence_offset'])
        self.assertEqual(register.call_args.args[4],descriptor['proof'])

    def test_unsplit_descriptor_stays_in_root_and_disabled_profile_drops_old_channel(self):
        original,payload=self.compose(False)
        self.assertEqual(payload['ai_match_channel']['code_region'],'root')
        at=payload['ai_match_channel']['fence_offset']
        self.assertEqual(bytes.fromhex(payload['blob_hex'])[at:at+8],bytes.fromhex('bf3b03d5c0035fd6'))
        inherited=copy.deepcopy(original);inherited['ai_match_channel']=payload['ai_match_channel']
        profile=json.loads((RESOURCE/'native-route-templates.json').read_text())
        self.assertNotIn('ai_match_channel',compose(inherited,[],profile))

    def test_game_archive_replaces_all_new_helpers_including_stale_copies(self):
        helpers={name:(ROOT/(name+'.py')).read_text('utf8')for name in
                 ('ai_tactical_profiles','ai_division_sessions','ai_match_manager','ai_match_channel','ai_match_runtime','ai_match_state')}
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('embedded_gateway.pyc',bytecode('pass','embedded_gateway.py'))
            for name in helpers:z.writestr(name+'.pyc',b'stale')
            z.writestr('keep.bin',b'original')
        rebuilt=hook_archive(raw.getvalue(),'pass',helper_sources=helpers)
        with zipfile.ZipFile(io.BytesIO(rebuilt)) as z:
            self.assertEqual(z.read('keep.bin'),b'original')
            for name,source in helpers.items():
                self.assertEqual(z.namelist().count(name+'.pyc'),1)
                self.assertEqual(z.read(name+'.pyc'),bytecode(source,name+'.py'))


if __name__=='__main__':unittest.main()
