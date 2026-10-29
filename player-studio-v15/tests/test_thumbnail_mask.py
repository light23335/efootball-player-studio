import copy,json,struct,sys,tempfile,unittest,random
from pathlib import Path
from PIL import Image,ImageChops,ImageOps
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thumbnail_mask import personal_alpha,preview_masks,_switch_script,_soft_switch_script,_restore_v2_script,isolate_shader_map,MARKER,MARKER_PATH,MARKER_VARIATION,RENAMES,INSTANCE


class PersonalThumbnailMaskTests(unittest.TestCase):
    def profile(self):
        return json.loads((Path(__file__).resolve().parents[1]/'resources/native-thumbnail-mask.json').read_text('utf8'))

    def test_left_portrait_area_is_open_but_inner_edge_and_corners_remain(self):
        inner,outer=preview_masks()
        self.assertEqual(inner.getpixel((8,64)),255)
        self.assertEqual(inner.getpixel((2,64)),0)
        self.assertEqual(inner.getpixel((4,4)),0)
        self.assertEqual(inner.getbbox(),(4,4,124,124))
        self.assertEqual(ImageChops.difference(inner,ImageOps.mirror(inner)).getbbox(),None)
        self.assertEqual(outer.getbbox(),(0,0,128,128));self.assertEqual(outer.getpixel((0,0)),0)

    def test_mirror_changes_only_the_asymmetric_hidden_side(self):
        original=Image.new('RGBA',(128,128));a=preview_masks()[0]
        right=a.copy();right.paste(0,(0,0,29,128));original.putalpha(right)
        result=personal_alpha(original)
        self.assertEqual(result.tobytes(),a.tobytes())
        self.assertEqual(ImageChops.difference(result.crop((29,0,128,128)),right.crop((29,0,128,128))).getbbox(),None)

    def evaluate(self,data,source,refs):
        at=0
        def value():
            nonlocal at
            op=data[at];at+=1
            if op==0x20:
                index=struct.unpack_from('<i',data,at)[0];at+=4;return ('object',index)
            if op in (0x27,0x28):return op==0x27
            if op==0x42:
                at+=16;self.assertEqual(data[at],1);at+=17;return ('object',source)
            if op==0x68:
                self.fail('CallMath cannot be a SwitchValue index: native VM passes a null result pointer')
            if op==0x69:
                count=struct.unpack_from('<H',data,at)[0];at+=6
                self.assertEqual(data[at],0x42,'native SwitchValue index must expose a property/address')
                condition=value();choices=[]
                for _ in range(count):
                    case=value();at+=4;choices.append((case,value()))
                default=value();return next((v for k,v in choices if k==condition),default)
            self.fail(hex(op))
        return value(),at

    def test_exact_marker_selects_private_material_in_both_load_locations(self):
        p=self.profile();old=bytes.fromhex(p['front_object_hex'])
        script=old+b'\x69\x02\x00'+struct.pack('<I',145)+b'\x28'+struct.pack('<I',122)+b'\x27'+struct.pack('<I',136)
        refs=[-201,-202,-203];new,delta=_switch_script(script,p,refs)
        self.assertEqual(delta,100)
        for source in (refs[0],refs[1]):self.assertEqual(self.evaluate(new,source,refs)[0],('object',refs[2]))
        for source in (0,-119,-300,refs[2]):self.assertEqual(self.evaluate(new,source,refs)[0],('object',-119))
        # Reusing one widget for personal -> stock must restore the stock MI.
        self.assertEqual([self.evaluate(new,s,refs)[0][1]for s in (refs[0],0,refs[1],-300)],[-203,-119,-203,-119])
        self.assertIn(b'\x69\x02\x00'+struct.pack('<I',245),new)
        self.assertIn(b'\x28'+struct.pack('<I',222),new)

    def test_index_is_a_real_property_and_both_case_jump_boundaries_are_in_memory_units(self):
        p=self.profile();old=bytes.fromhex(p['front_object_hex'])
        trailer=b'\x69\x02\x00'+struct.pack('<I',145)+b'\x28'+struct.pack('<I',122)+b'\x27'+struct.pack('<I',136)
        new,_=_switch_script(old+trailer,p,[-201,-202,-203])
        count,end=struct.unpack_from('<HI',new,1)
        self.assertEqual((count,end),(3,138));self.assertEqual(new[7],0x42)
        # Field paths deserialize from 34 bytes to two native 8-byte pointers
        # and two tokens (18 bytes); object constants expand from 5 to 9.
        at=7+len(bytes.fromhex(p['f03_expression_hex']))
        self.assertEqual(struct.unpack_from('<I',new,at+5)[0],76)
        self.assertEqual(struct.unpack_from('<I',new,at+14+5)[0],98)
        self.assertEqual(new[at+28],0x42)
        self.assertEqual(struct.unpack_from('<I',new,at+28+34)[0],129)
        self.assertEqual(at+28+34+4+5+5,117)

    def test_unknown_widget_is_rejected_instead_of_changing_shared_materials(self):
        with self.assertRaises(ValueError):_switch_script(b'unknown widget',self.profile(),[-1,-2,-3])

    def test_soft_asset_cases_do_not_depend_on_added_hard_package_imports(self):
        p=self.profile();old=bytes.fromhex(p['front_object_hex'])
        trailer=b'\x69\x02\x00'+struct.pack('<I',145)+b'\x28'+struct.pack('<I',122)+b'\x27'+struct.pack('<I',136)
        fixed,delta=_soft_switch_script(old+trailer,p,-181)
        self.assertEqual(fixed[7],0x42,'Only real property IO is safe in the index term')
        self.assertEqual(fixed.count(b'\x68'+struct.pack('<i',-181)),4)
        for path in (MARKER_PATH,MARKER_VARIATION,RENAMES[INSTANCE]):
            self.assertIn(b'\x67\x1f'+(path+'.'+path.rsplit('/',1)[-1]).encode()+b'\0',fixed)
        self.assertEqual(struct.unpack_from('<I',fixed,3)[0],29+9+delta)
        v2,_=_switch_script(old+trailer,p,[-201,-202,-203])
        self.assertEqual(_restore_v2_script(v2,p),old+trailer)

    def test_private_shader_map_identity_changes_without_rewriting_shader_code(self):
        p=self.profile();key=bytes.fromhex(p['cooked_shader_map_id_hash']);source=b'shader code'+key+b'unchanged resource hash'
        result,report=isolate_shader_map(source,p)
        self.assertEqual(result[:11],source[:11]);self.assertEqual(result[31:],source[31:])
        self.assertNotEqual(result[11:31],key);self.assertTrue(report['compiled_shader_code_unchanged'])
        self.assertEqual(isolate_shader_map(source,p)[0],result)
        with self.assertRaises(ValueError):isolate_shader_map(source+key,p)

    def test_shader_codec_handles_literals_overlap_and_incompressible_data(self):
        from thumbnail_shader import _compress,lz4_block
        rng=random.Random(42)
        for value in (b'',b'a',b'a'*4000,b'abcd'*17000,bytes(range(256))*9,bytes(rng.randrange(256)for _ in range(6000))):
            self.assertEqual(lz4_block(_compress(value),len(value)),value)
        for bad,n in [(b'\x00\0\0',4),(b'\x10',1),(b'\xf0\xff',12),(b'\x01\x01\x00',10)]:
            with self.assertRaises(ValueError):lz4_block(bad,n)

    def test_native_shader_uv_fix_covers_every_pixel_type_and_preserves_vertex_code(self):
        from thumbnail_shader import patch_private_shader,lz4_block
        from native_art import Assets
        root=Path(__file__).resolve().parents[2]
        cache=root/'球员工坊-V17/library/versions/V17-1f38a585/containers'
        if not (cache/'resource-key.bin').is_file():self.skipTest('requires audited V17 assets')
        p=self.profile();cfg=p['inline_shader_uv'];source,_=Assets(cache).get(cfg['material'])
        result,report=patch_private_shader(source,p)
        self.assertEqual(report['pixel_shader_variants'],6);self.assertEqual(report['vertex_shaders_preserved'],2)
        def entries(raw):
            at=cfg['code_offset']+24;count=struct.unpack_from('<I',raw,at-4)[0]
            hashes=[raw[at+n*20:at+(n+1)*20]for n in range(count)];at+=count*20+4;values=[]
            for _ in range(count):
                n=struct.unpack_from('<I',raw,at)[0];code=raw[at+4:at+4+n];size,freq=struct.unpack_from('<IB',raw,at+4+n);at+=9+n
                values.append((lz4_block(code,size)if n!=size else code,freq))
            self.assertEqual(at,len(raw));return hashes,values
        old_hashes,old=entries(source);new_hashes,new=entries(result)
        self.assertEqual(new_hashes,sorted(new_hashes))
        seen=set()
        for offset,index in cfg['frozen_resource_indices']:
            remapped=struct.unpack_from('<I',result,offset)[0];seen.add(index)
            before,freq=old[index];after,new_freq=new[remapped];self.assertEqual(freq,new_freq)
            expected=before if freq==0 else before.replace(b'vec2(2.265625e-01,3.125000e-02)',b'vec2(0.000000e+00,0.000000e+00)').replace(b'vec2(9.375000e-01,9.375000e-01)',b'vec2(1.000000e+00,1.000000e+00)')
            self.assertEqual(after,expected)
        self.assertEqual(seen,set(range(8)))
        with self.assertRaises(ValueError):patch_private_shader(result,p)


if __name__=='__main__':unittest.main()
