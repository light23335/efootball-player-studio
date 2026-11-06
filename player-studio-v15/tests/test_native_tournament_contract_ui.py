import json,struct,unittest
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
from tournament_entry import text_groups

RESOURCE=Path(__file__).resolve().parents[1]/'resources/tournament_schedule_ui/native-contract.json'
class ChanceButtonTests(unittest.TestCase):
    def test_original_bulk_quantity_caps_to_chances_remaining_pool_and_ten(self):
        from test_tournament_home import original_engine
        raw=original_engine()
        for balance in (1,2,7,8,9,10,12):
            for pool in (1,5,9,118):
                v=Uc(UC_ARCH_ARM64,UC_MODE_ARM);record,stop=0x20000000,0x40000000
                for at,size in ((0x356a000,4096),(record,4096),(stop,4096)):v.mem_map(at,size)
                v.mem_write(0x356a000,raw[0x3566000:0x3567000])
                for offset,value in ((0,10),(0x10,balance),(0x100,10),(0xd8,pool)):
                    v.mem_write(record+offset,struct.pack('<I',value))
                v.reg_write(UC_ARM64_REG_X0,record);v.reg_write(UC_ARM64_REG_X30,stop)
                v.emu_start(0x356a378,stop,count=100)
                self.assertEqual(v.reg_read(UC_ARM64_REG_X0),min(10,balance,pool),(balance,pool))

    def vm(self):
        data=json.loads(RESOURCE.read_text('utf8'));v=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        code,objects,stack,stop=0x10000000,0x20000000,0x30000000,0x40000000
        for at,size in ((code,4096),(objects,0x5000),(stack,0x10000),(stop,4096),(0x3585000,4096),(0x81ef000,0x2000)):
            v.mem_map(at,size)
        v.mem_write(code,bytes.fromhex(data['body_hex']));v.reg_write(UC_ARM64_REG_SP,stack+0xf000)
        v.reg_write(UC_ARM64_REG_X30,stop);calls=[]
        def oncode(vm,at,size,_):
            if at==0x81efe78:
                calls.append((vm.reg_read(UC_ARM64_REG_X0),vm.reg_read(UC_ARM64_REG_X1)))
                vm.reg_write(UC_ARM64_REG_PC,vm.reg_read(UC_ARM64_REG_X30))
            elif at==0x3585b58:vm.emu_stop()
        v.hook_add(UC_HOOK_CODE,oncode)
        return data,v,code,objects,stop,calls

    def test_reserved_chance_labels_replace_both_placeholders_for_every_kind(self):
        for aid in (1500000000,1599999999):
            for kind in range(6):
                _,v,code,obj,stop,calls=self.vm();initial=v.reg_read(UC_ARM64_REG_SP)
                v.mem_write(obj+0x1380,struct.pack('<Q',aid))
                for reg,value in ((UC_ARM64_REG_X0,obj),(UC_ARM64_REG_X1,kind),(UC_ARM64_REG_X2,obj+0x2000),(UC_ARM64_REG_X3,obj+0x2100)):
                    v.reg_write(reg,value)
                v.reg_write(UC_ARM64_REG_X19,9876);v.emu_start(code,stop,count=500)
                self.assertEqual(calls,[(obj+0x2000,(1142<<16)|63000),(obj+0x2100,(1142<<16)|63001)])
                self.assertEqual(v.reg_read(UC_ARM64_REG_SP),initial);self.assertEqual(v.reg_read(UC_ARM64_REG_X19),9876)

    def test_normal_agent_keeps_original_prologue_and_arguments(self):
        for aid,kind in ((1366,0),(1499999999,0),(1600000000,1),(1500000000,6)):
            _,v,code,obj,stop,calls=self.vm();initial=v.reg_read(UC_ARM64_REG_SP)
            v.mem_write(obj+0x1380,struct.pack('<Q',aid));v.reg_write(UC_ARM64_REG_X0,obj)
            v.reg_write(UC_ARM64_REG_X1,kind);v.reg_write(UC_ARM64_REG_X2,obj+0x2000);v.reg_write(UC_ARM64_REG_X3,obj+0x2100)
            v.reg_write(UC_ARM64_REG_X29,1234);v.emu_start(code,stop,count=500)
            self.assertEqual(calls,[]);self.assertEqual(v.reg_read(UC_ARM64_REG_SP),initial-0x60)
            self.assertEqual(struct.unpack('<QQ',v.mem_read(initial-0x60,16)),(1234,stop))
            self.assertEqual(v.reg_read(UC_ARM64_REG_X0),obj);self.assertEqual(v.reg_read(UC_ARM64_REG_X1),kind)

    def test_zero_expiry_takes_original_no_countdown_text_path(self):
        data,v,_,obj,stop,calls=self.vm();site=0x3586a40
        raw=next(p for p in data['native_probes']if p['file_offset']==site-0x4000)
        v.mem_map(0x3586000,4096);v.mem_write(site,bytes.fromhex(raw['expected_hex']))
        v.reg_write(UC_ARM64_REG_X20,obj+0x2000)
        v.mem_write(v.reg_read(UC_ARM64_REG_SP)+0x24,bytes(4))
        v.emu_start(site,0x3586a58,count=100)
        self.assertEqual(calls,[(obj+0x2000,0x2300394)])

    def test_localized_labels_exist_and_have_no_format_placeholders(self):
        from custom_boosters import text_key
        booster_keys={text_key(i)+offset for i in range(1,1024)for offset in (0,1)}
        self.assertFalse(booster_keys & {63000,63001})
        for locale in ('zha','chi','eng'):
            rows=text_groups(locale);items=next(r['items']for r in rows if r['id']==1142)
            for key in (63000,63001):self.assertNotIn('%',items[key]);self.assertTrue(items[key])

    def test_original_zero_count_details_now_build_native_chance_labels(self):
        # Start before the stock count/kind/price branches and execute the
        # ORIGINAL chance-option builder, not a mock of that builder. Only
        # agent storage, strings and vector allocation are fixture services.
        for count,patched in ((0,False),(0,True),(1,False),(1,True)):
            data,v,code,obj,stop,_=self.vm();heap=0x22000000
            v.mem_map(heap,0x10000)
            pages={0x3585000,0x81ef000,0x81f0000}
            for p in data['native_probes']:
                at=p.get('address',p['file_offset']+0x4000);raw=bytes.fromhex(p['expected_hex'])
                for page in range(at&~4095,(at+len(raw)+4095)&~4095,4096):
                    if page not in pages:v.mem_map(page,4096);pages.add(page)
                v.mem_write(at,raw)
            services=(0x7a87db8,0x7a729c8,0x7a76900,0x2fde568,0x318916c,
                      0x3588464,0x74fd90c,0x2fc4cd8,0x3589018,0x8c1bc60)
            for at in services:
                if at&~4095 not in pages:v.mem_map(at&~4095,4096);pages.add(at&~4095)
            v.mem_map(0x33000000,4096);v.reg_write(UC_ARM64_REG_TPIDR_EL0,0x33000000)
            sp=v.reg_read(UC_ARM64_REG_SP)
            def put(at,fmt,*values):v.mem_write(at,struct.pack(fmt,*values))
            put(obj+0x1380,'<Q',1500000001)
            put(obj+0x1390,'<QQQ',heap+0x4000,heap+0x4000,heap+0x5000)
            put(obj+0x3028,'<Q',obj+0x3100)
            put(obj+0x4010,'<I',count)
            put(sp+0x178,'<I',count);put(sp+0x2a8,'<I',0)
            put(sp+0x2e8,'<QQ',heap,heap+4) # native NONE kind
            put(sp+0x68,'<QQ',heap+0x100,heap+0x100) # empty paid price list
            put(sp+0xb8,'<QQQ',heap+0x2000,heap+0x2000,heap+0x3000)
            v.reg_write(UC_ARM64_REG_X21,obj)
            v.reg_write(UC_ARM64_REG_X19,sp+0x168)
            calls=[];rows=[]
            def ret(value=None):
                if value is not None:v.reg_write(UC_ARM64_REG_X0,value)
                v.reg_write(UC_ARM64_REG_PC,v.reg_read(UC_ARM64_REG_X30))
            def small(at,text):
                b=text.encode();v.mem_write(at,bytes([len(b)*2])+b+b'\0'+bytes(22-len(b)))
            def execute(uc,at,size,_):
                a=uc.reg_read(UC_ARM64_REG_X0);b=uc.reg_read(UC_ARM64_REG_X1)
                if at==0x358161c and patched:
                    entry=data['extra_entries'][0];uc.reg_write(UC_ARM64_REG_PC,code+entry['entry_offset'])
                elif at==0x7a87db8:ret(obj+0x3000)
                elif at==0x7a729c8:ret(obj+0x3100)
                elif at==0x7a76900:ret(obj+0x4000)
                elif at==0x2fde568:v.mem_write(a,bytes(v.mem_read(b,0x200)));ret()
                elif at==0x8c1bc60:
                    length=uc.reg_read(UC_ARM64_REG_X2)
                    if length:v.mem_write(a,bytes(v.mem_read(b,length)))
                    ret()
                elif at==0x81efe78:
                    calls.append(b);small(a,'Chance');ret()
                elif at==0x74fd90c:small(a,str(struct.unpack('<I',v.mem_read(b+0x10,4))[0]));ret()
                elif at==0x318916c:
                    end=struct.unpack('<Q',v.mem_read(a+8,8))[0]
                    v.mem_write(end,bytes(v.mem_read(b,24)));put(a+8,'<Q',end+24);ret()
                elif at==0x3588464:ret(0)
                elif at==0x2fc4cd8:ret()
                elif at==0x3589018:
                    rows.append(bytes(v.mem_read(b,0xb0)));v.mem_write(a,rows[-1]);ret()
            # Remove the label-only test fixture hook, which intercepts the
            # same localization service without writing its string object.
            # Its no-op return is overridden by this later, explicit service.
            v.hook_add(UC_HOOK_CODE,execute)
            try:v.emu_start(0x35815bc,0x3581cf0,count=5000)
            except Exception as exc:
                raise AssertionError(f'native details PC={v.reg_read(UC_ARM64_REG_PC):x}')from exc
            if count==0 and not patched:
                self.assertEqual(rows,[]);self.assertEqual(calls,[])
                continue
            self.assertEqual(len(rows),1)
            begin,end,_=struct.unpack_from('<QQQ',rows[0])
            self.assertEqual(end-begin,2*24)
            self.assertEqual(bytes(v.mem_read(begin+1,6)),b'Chance')
            self.assertEqual(struct.unpack_from('<III',rows[0],0x18),(0,3,0))
            self.assertEqual(struct.unpack_from('<I',rows[0],0x24)[0],1)
            self.assertEqual(struct.unpack('<I',v.mem_read(sp+0x178,4))[0],count)
            self.assertEqual(struct.unpack('<QQ',v.mem_read(sp+0x68,16)),(heap+0x100,heap+0x100))
            self.assertEqual(v.reg_read(UC_ARM64_REG_SP),sp)
            self.assertIn((1142<<16)|253,calls)

    def test_zero_count_branch_is_scoped_and_preserves_machine_state(self):
        for aid,target in ((1366,0x358163c),(1499999999,0x358163c),
                           (1500000000,0x3581620),(1599999999,0x3581620),
                           (1600000000,0x358163c)):
            data,v,code,obj,stop,_=self.vm();v.mem_map(0x3581000,4096)
            put=lambda at,fmt,*x:v.mem_write(at,struct.pack(fmt,*x))
            put(obj+0x1380,'<Q',aid)
            registers=[UC_ARM64_REG_X0+i for i in range(29)]+[UC_ARM64_REG_X29,UC_ARM64_REG_X30]
            for i,reg in enumerate(registers):v.reg_write(reg,0xabc000+i)
            v.reg_write(UC_ARM64_REG_X21,obj);v.reg_write(UC_ARM64_REG_X10,0)
            v.reg_write(UC_ARM64_REG_NZCV,0xa0000000)
            before=[v.reg_read(r)for r in registers];sp=v.reg_read(UC_ARM64_REG_SP)
            v.emu_start(code+data['extra_entries'][0]['entry_offset'],target,count=500)
            # X16 is the installer's documented indirect-branch scratch.
            after=[v.reg_read(r)for r in registers]
            self.assertEqual(before[:16]+before[17:],after[:16]+after[17:])
            self.assertEqual(v.reg_read(UC_ARM64_REG_NZCV),0xa0000000)
            self.assertEqual(v.reg_read(UC_ARM64_REG_SP),sp)

if __name__=='__main__':unittest.main()
