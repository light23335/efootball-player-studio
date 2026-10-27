"""Execute the original V17 parser/UI with the capacity hooks in ARM64.

Only allocator, localization and parameter lookup services are stubbed. The
real native list loops, vector growth, slot filtering and stack epilogues run.
"""
import copy
import io
import json
import os
from pathlib import Path
import struct
import sys
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE), str(SOURCE/'maintenance')]
APK = Path(os.environ.get('STUDIO_TEST_APK', str(SOURCE.parent.parent/'73efootball安装包及资源/73efootball-V17.apk')))


@unittest.skipUnless(APK.is_file(), 'requires original V17 engine')
class SkillCapacityNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import unicorn
        from unicorn import arm64_const
        from elftools.elf.elffile import ELFFile
        from build_skill_capacity import build
        cls.u, cls.r = unicorn, arm64_const
        with zipfile.ZipFile(APK) as z: cls.engine = z.read('lib/arm64-v8a/libUE4.so')
        cls.segments = [(s['p_vaddr'], s['p_offset'], s['p_filesz'], s['p_memsz'])
                        for s in ELFFile(io.BytesIO(cls.engine)).iter_segments() if s['p_type']=='PT_LOAD']
        cls.data = build(cls.engine)
        cls.params = {int(k): int(v) for k,v in json.loads((SOURCE/'resources/catalog.json').read_text(encoding='utf8'))['PARAMETER_BY_SKILL'].items()}
        cls.params.update({75+i:147+i for i in range(4)})

    def machine(self,widgets_enabled=True):
        u,r=self.u,self.r
        vm=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
        for a,n in ((0x30000000,0x10000),(0x40000000,0x20000),
                    (0x50000000,0x802000),(0x60000000,0x200000)):
            vm.mem_map(a,n)
        vm.reg_write(r.UC_ARM64_REG_SP,0x40010000)
        vm.reg_write(r.UC_ARM64_REG_TPIDR_EL0,0x4001f000)
        bundle=self.data['bundles'][0];body=bytearray.fromhex(bundle['body_hex'])
        for at,target in bundle['absolute_fixups']:struct.pack_into('<Q',body,at,target)
        for at,size in bundle['writable_fixups']:struct.pack_into('<Q',body,at,0x50000000)
        vm.mem_write(0x30000000,bytes(body))
        entries={row['address']:0x30000000+row.get('entry_offset',0)
                 for row in [bundle]+bundle['extra_entries']
                 if widgets_enabled or not row['name'].startswith('skill_widget_')}
        # The released four-skill protocol extends the existing enumeration
        # bound. Keep that exact instruction in the original list/count loop.
        bound={0x737a314:('w22',79),0x737b6a4:('w20',79)}
        self.heap=0x60010000;self.flags=set()
        def unmapped(m,access,address,size,value,user):
            page=address&~4095
            for va,off,filesz,memsz in self.segments:
                if va<=address<va+memsz:
                    m.mem_map(page,4096);low=max(page,va);high=min(page+4096,va+filesz)
                    if high>low:m.mem_write(low,self.engine[off+low-va:off+high-va])
                    return True
            raise AssertionError(('unmapped',hex(address),hex(m.reg_read(r.UC_ARM64_REG_PC))))
        def ret(m):m.reg_write(r.UC_ARM64_REG_PC,m.reg_read(r.UC_ARM64_REG_X30))
        def sso(m,a,text):
            value=text.encode();assert len(value)<=22
            m.mem_write(a,bytes([len(value)*2])+value+b'\0'+bytes(22-len(value)))
        def hook(m,pc,size,user):
            if pc in entries:m.reg_write(r.UC_ARM64_REG_PC,entries[pc]);return
            stub=getattr(self,'widget_stubs',{}).get(pc)
            if stub:stub(m);ret(m);return
            if pc in bound:
                regname,value=bound[pc];regid=getattr(r,'UC_ARM64_REG_'+regname.upper())
                # Compare replacement, then execute the unchanged b.eq/b.ne.
                operand=m.reg_read(regid)
                m.reg_write(r.UC_ARM64_REG_NZCV,0x60000000 if operand==value else 0x80000000 if operand<value else 0x20000000)
                m.reg_write(r.UC_ARM64_REG_PC,pc+4);return
            if pc in (0x737a328,0x737b678) and m.reg_read(r.UC_ARM64_REG_W22 if pc==0x737a328 else r.UC_ARM64_REG_W20)==74:
                m.reg_write(r.UC_ARM64_REG_PC,0x737a310 if pc==0x737a328 else 0x737b698)
                if pc==0x737b678:m.mem_write(m.reg_read(r.UC_ARM64_REG_SP)+4,bytes(4))
                return
            if pc in (0x2f37644,0x8c1bbd0):
                n=m.reg_read(r.UC_ARM64_REG_X0);a=self.heap;self.heap+=(n+15)//16*16
                m.reg_write(r.UC_ARM64_REG_X0,a);ret(m)
            elif pc==0x2f376d4:ret(m)
            elif pc==0x8c1bc60:
                dst,src,n=[m.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3)]
                m.mem_write(dst,bytes(m.mem_read(src,n)));ret(m)
            elif pc==0x8c1bca0:
                a=m.reg_read(r.UC_ARM64_REG_X0);m.reg_write(r.UC_ARM64_REG_X0,len(bytes(m.mem_read(a,100)).split(b'\0')[0]));ret(m)
            elif pc in (0x2f47358,0x81efde8):
                sso(m,m.reg_read(r.UC_ARM64_REG_X0),'S'+str(m.reg_read(r.UC_ARM64_REG_W1)));ret(m)
            elif pc==0x82bb60c:
                a=m.reg_read(r.UC_ARM64_REG_X0);m.reg_write(r.UC_ARM64_REG_W0,struct.unpack('<I',m.mem_read(a,4))[0]);ret(m)
            elif pc==0x82a2220:
                skill=m.reg_read(r.UC_ARM64_REG_W0);m.reg_write(r.UC_ARM64_REG_W0,self.params.get(skill,999));ret(m)
            elif pc==0x7a87f44:ret(m)
            elif pc==0x82a84d4:
                parameter=m.reg_read(r.UC_ARM64_REG_W1);out=m.reg_read(r.UC_ARM64_REG_X2)
                m.mem_write(out,struct.pack('<I',int(parameter in self.flags)));ret(m)
            elif pc==0x2f479c0:
                out,src=m.reg_read(r.UC_ARM64_REG_X0),m.reg_read(r.UC_ARM64_REG_X1)
                start,end,cap=struct.unpack('<QQQ',m.mem_read(out,24));n=(end-start)//24
                new=self.heap;self.heap+=(n+1)*24+16
                if n:m.mem_write(new,bytes(m.mem_read(start,n*24)))
                m.mem_write(new+n*24,bytes(m.mem_read(src,24)))
                m.mem_write(out,struct.pack('<QQQ',new,new+(n+1)*24,new+(n+1)*24));ret(m)
            elif pc in (0x8c1ec40,0x8c1bc00,0x7656708):raise AssertionError(('native abort',hex(pc)))
        vm.hook_add(u.UC_HOOK_MEM_UNMAPPED,unmapped);vm.hook_add(u.UC_HOOK_CODE,hook)
        return vm

    def helper(self,vm,name,*args):
        r=self.r
        for index,value in enumerate(args):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(index)),value)
        vm.reg_write(r.UC_ARM64_REG_X30,0x40000000)
        entry=self.data['bundles'][0]['helper_entries']['shared_'+name]
        vm.emu_start(0x30000000+entry,0x40000000,count=1000000)
        return vm.reg_read(r.UC_ARM64_REG_X0)

    def widget_fixture(self,vm,common,count,additional=True):
        r=self.r;owner=0x40006000;offset=0x1358 if additional else 0x1340
        table=owner+offset;vm.mem_write(table,struct.pack('<QQQ',table+8,0,0))
        rows=[];created=[];headings=[]
        def create(m):
            value=0x61000000+len(created)*256;created.append(value);m.reg_write(r.UC_ARM64_REG_X0,value)
        def set_row(m):
            a=m.reg_read(r.UC_ARM64_REG_X1);text,length=struct.unpack('<QI',m.mem_read(a,12))
            value=bytes(m.mem_read(text,max(0,length-1)*2)).decode('utf-16le')
            rows.append((m.reg_read(r.UC_ARM64_REG_X0),value,m.reg_read(r.UC_ARM64_REG_W2)))
        self.widget_stubs={0x302b480:lambda m:m.reg_write(r.UC_ARM64_REG_X0,common-0x30),
            0x305b6d4:lambda m:m.reg_write(r.UC_ARM64_REG_W0,count),
            0x305b714:lambda m:m.reg_write(r.UC_ARM64_REG_W0,1234),
            0x30468f0:lambda m:headings.append(m.reg_read(r.UC_ARM64_REG_X0)),
            0x305b398:lambda m:m.reg_write(r.UC_ARM64_REG_W0,1),
            0x305b4e8:lambda m:m.reg_write(r.UC_ARM64_REG_W0,1),
            0x3052434:create,0x3047108:set_row}
        self.helper(vm,'skill_widget_assign',table,0,0x62000000)
        for index in range(1,count+1):self.helper(vm,'skill_widget_assign',table,index,0x62000000+index*256)
        names,ids=0x4000b000,0x4000b020
        vm.mem_write(names,struct.pack('<QII',0x4000b100,count,count))
        vm.mem_write(ids,struct.pack('<QII',0x4000b900,count,count))
        for index in range(count):
            text=('技能 '+str(index+1)).encode('utf-16le')+b'\0\0';at=0x4000c000+index*64
            vm.mem_write(at,text);vm.mem_write(0x4000b100+index*16,struct.pack('<QII',at,len(text)//2,len(text)//2))
            vm.mem_write(0x4000b900+index*4,struct.pack('<I',index))
        return owner,names,ids,rows,created,headings

    def display_widgets(self,vm,owner,names,ids,additional):
        r=self.r
        for i,value in enumerate((owner,names,ids)):vm.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),value)
        vm.reg_write(r.UC_ARM64_REG_X30,0x40000000)
        before=vm.reg_read(r.UC_ARM64_REG_SP)
        vm.emu_start(0x30518dc if additional else 0x305149c,0x40000000,count=1000000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),before)

    def test_original_widget_guards_reproduce_reported_entirely_blank_sections(self):
        for additional,count in ((False,11),(False,20),(True,6),(True,10)):
            vm=self.machine(False);common=self.parse(vm,list(range(10)))
            owner,names,ids,rows,_,_=self.widget_fixture(vm,common,count,additional)
            self.display_widgets(vm,owner,names,ids,additional)
            self.assertEqual(rows,[])

    def test_final_widget_consumers_receive_every_innate_and_additional_label(self):
        for additional,count in ((False,11),(False,20),(False,21),(False,78),(False,100),
                                 (True,6),(True,10),(True,11),(True,78),(True,100),(True,5)):
            vm=self.machine();common=self.parse(vm,list(range(10)))
            owner,names,ids,rows,_,headings=self.widget_fixture(vm,common,count,additional)
            self.display_widgets(vm,owner,names,ids,additional)
            self.assertEqual([row[1] for row in rows],['技能 '+str(i+1) for i in range(count)])
            self.assertEqual(len(headings),1)

    def test_extended_additional_constructor_creates_actual_rows_up_to_100(self):
        for count,expected in ((100,100),(78,78),(11,11),(10,10),(6,6),(5,1)):
            vm=self.machine();common=self.parse(vm,list(range(count)))
            owner,names,ids,_,created,_=self.widget_fixture(vm,common,0)
            vm.reg_write(self.r.UC_ARM64_REG_X19,owner);vm.reg_write(self.r.UC_ARM64_REG_X20,0x63000000)
            vm.emu_start(0x304bb0c,0x304be70 if count>5 else 0x304bb10,count=1000000)
            self.assertEqual(len(created),expected)
            if count>5:
                for index,widget in enumerate(created,1):self.assertEqual(self.helper(vm,'skill_widget_find',owner+0x1358,index),widget)

    def test_secondary_skill_info_modal_builds_all_rows_up_to_100(self):
        for count,expected in ((100,100),(78,78),(11,11),(10,10),(6,6),(5,5)):
            vm=self.machine();r=self.r;observed=[];owner=0x40006000
            vm.mem_write(owner+0x12e8,struct.pack('<QII',0x40009000,count,count))
            vm.mem_write(0x40009000,struct.pack('<'+'I'*count,*range(100,100+count)))
            self.widget_stubs={0x30fb51c:lambda m:observed.append(m.reg_read(r.UC_ARM64_REG_W2))}
            vm.reg_write(r.UC_ARM64_REG_X19,owner);vm.reg_write(r.UC_ARM64_REG_X20,0x63000000)
            vm.emu_start(0x30fb0dc,0x30fb1b0,count=1000000)
            self.assertEqual(observed,list(range(100,100+expected)))

    def parse(self,vm,skills,cid=90159685046698,serial=1):
        r=self.r;source=0x40001000;common=0x40002030
        vm.mem_write(common+8,struct.pack('<QQ',cid,serial))
        vm.mem_write(source+0xd8,struct.pack('<QQ',0x40003000,0x40003000+len(skills)*4))
        if skills:vm.mem_write(0x40003000,struct.pack('<'+'I'*len(skills),*skills))
        vm.mem_write(common+0x60,b'G'*0x24)
        vm.reg_write(r.UC_ARM64_REG_X19,source);vm.reg_write(r.UC_ARM64_REG_X20,common)
        vm.emu_start(0x765613c,0x765638c,count=100000)
        self.assertEqual(bytes(vm.mem_read(common+0x60,4)),b'GGGG')
        self.assertEqual(bytes(vm.mem_read(common+0x78,12)),b'G'*12)
        return common

    def listing(self,vm,common,additional=True,skills=()):
        r=self.r;names=0x40004000;ids=0x40004030
        vm.mem_write(names,bytes(24));vm.mem_write(ids,bytes(24))
        vm.mem_write(common+0xf0,struct.pack('<I',1))
        vm.reg_write(r.UC_ARM64_REG_X0,common-0x30)
        vm.reg_write(r.UC_ARM64_REG_X1,names);vm.reg_write(r.UC_ARM64_REG_X2,ids)
        vm.reg_write(r.UC_ARM64_REG_X30,0x40000000)
        self.flags={self.params[i] for i in skills}
        before=vm.reg_read(r.UC_ARM64_REG_SP)
        vm.emu_start(0x737a66c if additional else 0x737a2b0,0x40000000,count=1000000)
        self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),before)
        start,end,_=struct.unpack('<QQQ',vm.mem_read(ids,24));n=(end-start)//4
        values=list(struct.unpack('<'+'I'*n,vm.mem_read(start,n*4))) if n else []
        a,z,_=struct.unpack('<QQQ',vm.mem_read(names,24))
        self.assertEqual((z-a)//24,n)
        labels=[bytes(vm.mem_read(p+1,vm.mem_read(p,1)[0]//2)).decode() for p in range(a,z,24)]
        return values,labels

    def test_parser_accepts_up_to_100_without_touching_adjacent_fields(self):
        for n in [*range(11),11,20,21,50,78,99,100,101]:
            vm=self.machine();common=self.parse(vm,list(range(n)))
            self.assertEqual(list(struct.unpack('<5I',vm.mem_read(common+0x64,20))),list(range(min(n,5)))+[74]*max(0,5-n))

    def test_additional_list_contains_all_ten_native_ids_and_labels(self):
        for skills in (list(range(10)),[1,2,7,15,17,20,75,76,77,78]):
            vm=self.machine();common=self.parse(vm,skills)
            ids,labels=self.listing(vm,common)
            self.assertEqual(ids,skills)
            self.assertEqual(labels,['S'+str(self.params[i]) for i in skills])

    def test_100_additional_slots_snapshot_names_and_capacity_clamp(self):
        valid=[i for i in range(79) if i!=74]
        for count in (11,21,78,100,101):
            skills=[valid[i%len(valid)] for i in range(count)]
            vm=self.machine();common=self.parse(vm,skills)
            ids,labels=self.listing(vm,common)
            self.assertEqual(ids,skills[:100])
            self.assertEqual(labels,['S'+str(self.params[i]) for i in skills[:100]])

    def test_all_available_innate_skills_display_without_additional(self):
        innate=[i for i in range(79) if i!=74]
        vm=self.machine();common=self.parse(vm,[])
        ids,labels=self.listing(vm,common,False,innate)
        self.assertEqual(ids,innate)
        self.assertEqual(len(labels),len(innate))

    def test_twenty_innate_plus_ten_additional_are_separate(self):
        innate=list(range(30));additional=[i for i in range(30,79) if i!=74]
        vm=self.machine();common=self.parse(vm,additional)
        ids,labels=self.listing(vm,common,False,innate+additional)
        self.assertEqual(ids,innate);self.assertEqual(len(labels),30)
        self.assertEqual(self.listing(vm,common)[0],additional)
        vm.reg_write(self.r.UC_ARM64_REG_X0,common-0x30)
        vm.reg_write(self.r.UC_ARM64_REG_X30,0x40000000)
        self.flags={self.params[i] for i in innate+additional}
        vm.emu_start(0x737b638,0x40000000,count=1000000)
        self.assertEqual(vm.reg_read(self.r.UC_ARM64_REG_W0),30)

    def test_normal_player_keeps_five_slots(self):
        vm=self.machine();common=self.parse(vm,[1,2])
        ids,_=self.listing(vm,common)
        self.assertEqual(ids,[1,2,74,74,74])

    def test_six_to_ten_padding_and_editing_back_to_five(self):
        vm=self.machine()
        for n in (100,10,6,9,5,0,10):
            skills=[i%74 for i in range(n)]
            common=self.parse(vm,skills)
            ids,_=self.listing(vm,common)
            width=n if n>5 else 5
            self.assertEqual(ids,skills+[74]*(width-n))

    def test_two_owned_copies_and_hash_collisions_do_not_share_skills(self):
        vm=self.machine()
        for cid,serial,skills in ((12345,1,list(range(10))), (12345,2,list(range(10,20))),
                                  (12345+65536,1,list(range(20,30)))):
            self.parse(vm,skills,cid,serial)
        for cid,serial,skills in ((12345,1,list(range(10))), (12345,2,list(range(10,20))),
                                  (12345+65536,1,list(range(20,30)))):
            common=0x40002030;vm.mem_write(common+8,struct.pack('<QQ',cid,serial))
            self.assertEqual(self.listing(vm,common)[0],skills)

    def test_original_wire_parameters_activate_all_ten_without_changing_saved_values(self):
        import marshal,types
        from apk_literals import module_reader
        pending=[module_reader(APK)('player_parameters')];found=[]
        while pending:
            code=pending.pop()
            if code.co_name=='effective_parameters':found.append(code)
            for value in code.co_consts:
                if isinstance(value,types.CodeType):pending.append(value)
                elif isinstance(value,bytes) and value[:1] in (b'c',b'\xe3'):
                    try:child=marshal.loads(value)
                    except (ValueError,EOFError,TypeError):continue
                    if isinstance(child,types.CodeType):pending.append(child)
        self.assertEqual(len(found),1)
        self.assertEqual(set(found[0].co_names),{'owned_parameters','len','get','isinstance','list','type','int','PARAMETER_BY_SKILL'})
        function=types.FunctionType(found[0],{'owned_parameters':lambda p:list(p['parameters']),
                                               'PARAMETER_BY_SKILL':{k:v for k,v in self.params.items() if v<147}})
        player={'parameters':[0]*147,'additional_skill_id':list(range(20,30))}
        for skill in range(20):player['parameters'][self.params[skill]]=1
        before=copy.deepcopy(player);wire=function(player)
        self.assertEqual(player,before)
        for skill in range(30):self.assertEqual(wire[self.params[skill]],1,skill)
        self.assertEqual(len(wire),147)


if __name__=='__main__':unittest.main()
