"""Execute the original V17 special DTO converter and registered-slot counter.

The fixture supplies DTO memory and explicit allocator/string/formation services;
the original initial-settings branch, identity loops, rental conversion, native
team-key setter, rental predicate, and 23-slot counter all execute unchanged.
"""
import copy
import hashlib
import struct
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def convert_special(payload):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED
    import unicorn.arm64_const as R
    raw=(ROOT.parent/'.work/xi-v17-gameplay-compare/v17-engine.so').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(0x100000,0x700000)
    sp=0x7f0000;native=0x110000;dto=0x120000;heap=[0x200000]
    def alloc(n):
        at=heap[0];heap[0]+=(n+31)&~31;return at
    def put(at,fmt,*values):u.mem_write(at,struct.pack(fmt,*values))
    def read(at,fmt):return struct.unpack(fmt,u.mem_read(at,struct.calcsize(fmt)))
    def sso(at,value):
        b=value.encode();assert len(b)<=22
        u.mem_write(at,bytes([len(b)*2])+b+b'\0'+bytes(22-len(b)))
    def vector(at,b):
        start=alloc(len(b)+16);u.mem_write(start,b);put(at,'<QQQ',start,start+len(b),start+len(b))
    def memory(_u,access,address,size,value,data):
        page=address&~4095;u.mem_map(page,4096)
        off=page if page<0x2e00000 else page-0x4000
        if 0<=off<len(raw):u.mem_write(page,raw[off:off+4096])
        return True
    u.hook_add(UC_HOOK_MEM_UNMAPPED,memory)
    # ELF-relative GOT slots are resolved explicitly, as the Android loader does.
    memory(u,0,0x99e6000,0,0,None)
    put(0x99e6928,'<Q',0x130000);put(0x130000,'<I4xQQ',0xffffffff,0,0)
    put(0x99e6930,'<Q',0x130020);put(0x130020,'<H6xQQ',0xffff,0,0)
    put(0x99e6850,'<Q',0x130040);put(0x130040,'<I',0xffffffff)
    put(dto+0xb0,'<I',payload['rental_team_id'])
    put(dto+0xd0,'<I',payload.get('liveupdate_version',0))
    sso(dto+0xd8,payload.get('initial_settings','YES'))
    refs=payload['squad_data']['player_list']
    vector(dto,b''.join(struct.pack('<QQI4x',p['gameplayer_id']['id'],p['gameplayer_id'].get('serial',0),p.get('uniform_number',0))for p in refs))
    coaches=payload['squad_data'].get('coach',[])
    vector(dto+0x18,b''.join(struct.pack('<QQ',p['coach_id']['id'],p['coach_id'].get('serial',0))for p in coaches))
    rows=payload['rental_gameplayer_list'];begin=alloc(len(rows)*0x148+16)
    put(dto+0xb8,'<QQQ',begin,begin+len(rows)*0x148,begin+len(rows)*0x148)
    for i,p in enumerate(rows):
        at=begin+i*0x148;gid=p['gameplayer_id']
        put(at,'<QQ',gid['id'],gid.get('serial',0))
        put(at+0x90,'<I',p.get('initial_base_team_id',0))
        put(at+0x110,'<I',p.get('initial_base_national_team_id',0))
        put(at+0xf0,'<I',p.get('rental_match_left',0))
        sso(at+0xb8,p.get('type','RENTAL'));sso(at+0x60,p.get('is_lock','NO'))
        vector(at+0x98,struct.pack('<'+'I'*len(p.get('parameters',[])),*p.get('parameters',[])))
    # These enumeration fixtures are independent of the converter's comparisons.
    for i,v in enumerate(('NO','YES')):sso(0x140000+i*32,v)
    # Run the actual native type-string initializers: index 2 is RENTAL.
    # This verifies the JSON text-to-native enum, in addition to is_rental.
    memory(u,0,0xa5a5000,0,0,None);memory(u,0,0xa5a7000,0,0,None)
    put(0xa5a5208,'<B',1);u.reg_write(R.UC_ARM64_REG_X19,0xa5a5208)
    u.emu_start(0x7619a3c,0x7619bc0,count=1000)
    stop=0x150000;trace=[];parameters={};ordinary=[]
    def ret(value=None):
        if value is not None:u.reg_write(R.UC_ARM64_REG_X0,value)
        u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
    def callback(_u,at,size,data):
        x=lambda n:u.reg_read(getattr(R,'UC_ARM64_REG_X'+str(n)))
        if at in(0x7655704,0x7652c74,0x7655bf8,0x7a88330,0x7a81758):trace.append(hex(at))
        if at==0x76476ec:ret(0x140000+x(0)*32)
        elif at==0x8c1bca0:
            b=bytes(u.mem_read(x(0),128)).split(b'\0')[0];ret(len(b))
        elif at==0x8c1c1f0:
            a,b,n=x(0),x(1),x(2);ret(0 if bytes(u.mem_read(a,n))==bytes(u.mem_read(b,n))else 1)
        elif at in(0x2f3877c,0x2f46d10):
            a,b,n=x(0),x(1),x(2);sso(a,bytes(u.mem_read(b,n)).decode());ret(a)
        elif at in(0x2f37644,0x8c1bbd0):ret(alloc(x(0)))
        elif at==0x30403a0:
            a,p=x(0),x(1);b,e,c=read(a,'<QQQ');data=bytes(u.mem_read(b,e-b))if b else b''
            data+=bytes(u.mem_read(p,0xf0));n=alloc(len(data));u.mem_write(n,data);put(a,'<QQQ',n,n+len(data),n+len(data));ret(a)
        elif at==0x2fe01cc:
            a,b,e=x(0),x(1),x(2);data=bytes(u.mem_read(b,e-b));n=alloc(len(data)+16);u.mem_write(n,data);put(a,'<QQQ',n,n+len(data),n+len(data));ret(a)
        elif at in(0x321c090,0x82b6220,0x7a8f994,0x2f376d4,0x7a811c8,0x82a84c0,0x765b88c,0x7a81864,0x7a818c4,0x7a81924,0x2f49320):ret()
        elif at in(0x7a7fb88,0x7653828,0x7a80dac):ret()
        elif at in(0x7a7fe98,0x7a7febc):ret(0)
        elif at==0x82a907c:parameters[(x(0),x(1))]=x(2);ret()
        elif at==0x6774740:ret(0) # deterministic encryption key service only
        elif at==0x7b907a4:put(x(1),'<I',x(0));ret()
        elif at==0x82468d4:ret(0x160000)
        elif at==0x823c9d4:
            put(0x160100,'<I',x(1));ret(0x160100)
        elif at in(0x82b4a74,0x82b4a7c):ret(0) # names are covered by identity native tests
        elif at==0x7bab3b8:
            ordinary.append(True);ret(0)
        elif at==stop:u.emu_stop()
    u.hook_add(UC_HOOK_CODE,callback)
    u.reg_write(R.UC_ARM64_REG_SP,sp);u.reg_write(R.UC_ARM64_REG_TPIDR_EL0,0x170000)
    u.reg_write(R.UC_ARM64_REG_X0,native);u.reg_write(R.UC_ARM64_REG_X1,dto);u.reg_write(R.UC_ARM64_REG_X30,stop)
    u.emu_start(0x7655704,stop,count=250000)
    assert u.reg_read(R.UC_ARM64_REG_PC)==stop
    def call(at,a):
        u.reg_write(R.UC_ARM64_REG_X0,a);u.reg_write(R.UC_ARM64_REG_X30,stop);u.emu_start(at,stop,count=5000);return u.reg_read(R.UC_ARM64_REG_W0)
    b,e,c=read(native+0xc68,'<QQQ')
    rental_ids=[];rental_accept=[]
    for a in range(b,e,0xf0):
        rental_ids.append(read(a+8,'<QQ'));rental_accept.append(call(0x7a88330,a))
    # Continue through the same genuine special-slot getter and deep copy used
    # after the event-entry consumer (77f2d38 -> 7a438e0 -> 7a81d40).
    stored=call(0x7a438e0,0x190000)
    u.reg_write(R.UC_ARM64_REG_X1,native);call(0x7a81d40,stored)
    return {'registered':call(0x7a81758,native),'rental_count':call(0x7a81df0,native),
        'refs':[read(native+0x18+i*0x18+8,'<QQ')for i in range(23)],
        'rental_ids':rental_ids,'rental_accept':rental_accept,'trace':trace,
        'team_key':read(native+0xc64,'<I')[0],'initial_settings':read(native+0xc80,'<B')[0],
        'ordinary_read':bool(ordinary),'parameter_writes':len(parameters),
        'stored_registered':call(0x7a81758,stored),'stored_rental_count':call(0x7a81df0,stored),
        'stored_refs_unchanged':bytes(u.mem_read(stored+0x18,23*24))==bytes(u.mem_read(native+0x18,23*24))}


def fixture(team=54):
    refs=[{'gameplayer_id':{'id':1000+i,'serial':0},'uniform_number':i+1}for i in range(23)]
    return {'rental_team_id':team,'initial_settings':'YES','squad_data':{'player_list':refs},
        'rental_gameplayer_list':[dict(p,type='RENTAL',rental_match_left=99,parameters=[0]*147)for p in copy.deepcopy(refs)]}


class SpecialContractNativeTests(unittest.TestCase):
    def test_actual_converter_populates_twenty_three_registered_and_rental_slots(self):
        for team in(54,49206):
            p=fixture(team);out=convert_special(p)
            self.assertEqual((out['registered'],out['rental_count']),(23,23))
            self.assertEqual((out['stored_registered'],out['stored_rental_count']),(23,23))
            self.assertTrue(out['stored_refs_unchanged'])
            self.assertEqual(out['refs'],out['rental_ids'])
            self.assertEqual(out['rental_accept'],[1]*23)
            self.assertEqual(out['team_key'],team<<14)
            self.assertEqual(out['initial_settings'],1)
            self.assertFalse(out['ordinary_read'])

    def test_rentals_cannot_substitute_for_missing_registered_slot(self):
        p=fixture();p['squad_data']['player_list']=p['squad_data']['player_list'][:22]
        out=convert_special(p)
        self.assertEqual((out['registered'],out['rental_count']),(22,23))

    def test_expired_or_wrong_serial_rentals_are_rejected_by_original_native_code(self):
        p=fixture();p['rental_gameplayer_list'][0]['rental_match_left']=0
        p['rental_gameplayer_list'][1]['gameplayer_id']['serial']=88
        out=convert_special(p)
        self.assertEqual((out['registered'],out['rental_count']),(23,22))
        self.assertEqual(out['rental_accept'],[0]+[1]*21)


if __name__=='__main__':unittest.main()
