import copy,hashlib,json,struct,unittest,uuid
from functools import lru_cache
from pathlib import Path
import tournament_home as home
import tournament_rules as rules

PROFILE=Path(__file__).resolve().parents[1]/'resources/tournament_schedule_ui/native-home.json'


class HomeModelTests(unittest.TestCase):
    def state(self,kind='league',count=4,**kw):
        if kind in ('groups','league'):kw.setdefault('advance_per_group',2)
        return rules.start({'uuid':str(uuid.uuid4()),'name':'杯赛','team_ids':list(range(1,count+1)),
              'player_team_id':1,'stages':[{'type':kind,**kw},*([{'type':'knockout','advance':1}]if kind in ('groups','league')else[])]},17)

    def test_real_stage_counts_and_goal_with_next_fixture(self):
        s=self.state();m=home.model(s,{'1':'布莱顿'})
        self.assertEqual(m['goal'],'争取联赛晋级名次');self.assertEqual(m['remaining'],'3 场')
        self.assertIn('布莱顿',m['home']+m['away']);self.assertNotIn('%s',str(m))
        f=next(f for f in s['fixtures']if 1 in(f['home'],f['away']));f['played']=True
        self.assertEqual(home.model(s)['remaining'],'2 场')
        self.assertEqual(home.model(self.state('groups'))['goal'],'争取小组出线')

    def test_knockout_includes_future_rounds_and_single_leg_override(self):
        s=self.state('knockout',8,legs=2,round_overrides={'2':{'legs':1}})
        self.assertEqual(home.model(s)['remaining'],'5 场')
        self.assertEqual(home.model(self.state('knockout',2))['goal'],'争夺冠军')
        s['completed']=True
        self.assertEqual(home.model(s)['remaining'],'0 场')

    def test_publication_is_bounded_and_uses_owned_memory_only(self):
        texts=home.model(self.state());texts['home']='😀'*300
        raw=home.encode({205060988:texts})
        self.assertEqual(len(raw),home.SCHEMA['capacity']*home.SCHEMA['row_bytes'])
        self.assertEqual(struct.unpack_from('<I',raw)[0],205060988)
        self.assertEqual(raw[16+2*256:16+3*256].decode('utf-16le').rstrip('\0'),'😀'*63)
        with self.assertRaises(ValueError):home.encode({1120005:texts})
        buffer=bytearray(home.SCHEMA['bytes']);channel=home.Channel(buffer,0,lambda:None)
        channel.publish(raw,1)
        self.assertEqual(struct.unpack_from('<III',buffer),(1,1,2))
        channel.publish(home.encode({}),0)
        self.assertEqual(struct.unpack_from('<III',buffer),(1,0,4))
        self.assertEqual(len(buffer),home.SCHEMA['bytes'])
        buffer[home.SCHEMA['promotion_offset']:]=b'Z'*home.SCHEMA['promotion_bytes']
        channel.publish(home.encode({}),0)
        self.assertEqual(buffer[home.SCHEMA['promotion_offset']:],b'Z'*home.SCHEMA['promotion_bytes'])

    def test_membership_metadata_is_explicit_scalar_policy_and_does_not_reuse_reward_ids(self):
        policy={'kind':'national','entity_id':7}
        texts=home.model(self.state(),membership=policy);policy['entity_id']=108
        self.assertEqual(texts['membership']['entity_id'],7)
        raw=home.encode({205060988:texts})
        self.assertEqual(struct.unpack_from('<II',raw,3024),(1,7))
        texts['membership']={'kind':'club','entity_id':65590}
        self.assertEqual(struct.unpack_from('<II',home.encode({205060988:texts}),3024),(2,65590))
        for value in({'kind':'national','entity_id':0},{'kind':'national','entity_id':512},
                      {'kind':'club','entity_id':2**18},{'kind':'guess','entity_id':7},'national'):
            texts['membership']=value
            with self.assertRaises(ValueError):home.encode({205060988:texts})


def native_probe(options):
    """Execute emitted AArch64, stub only verified engine service calls."""
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    import unicorn.arm64_const as R
    p=json.loads(PROFILE.read_text('utf8'));body=bytearray.fromhex(p['body_hex'])
    assert hashlib.sha256(body).hexdigest()==p['body_sha256']
    code=0x200000;control=0x300000;stack=0x4f0000;frame=0x101000;actor=0x102000
    cls=0x103000;parent=0x104000;vtable=0x105000;getsuper=0x600000
    namefn=0x5de3160;setstr=0x3bd1b10;resume=p['address']+4
    for at,target in p['absolute_fixups']:struct.pack_into('<Q',body,at,target)
    for at,size in p['writable_fixups']:struct.pack_into('<Q',body,at,control)
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for at,size in ((0x100000,0x100000),(code,0x10000),(control,0x30000),
                    (0x4d0000,0x30000),(getsuper,0x1000),(namefn&~4095,0x1000),
                    (setstr&~4095,0x1000),(resume&~4095,0x1000)):uc.mem_map(at,size)
    uc.mem_write(code,bytes(body))
    def write(at,fmt,*v):uc.mem_write(at,struct.pack(fmt,*v))
    text=home.model(rules.start({'name':'联赛','team_ids':[1,2,3,4],'player_team_id':1,
          'stages':[{'type':'league','advance_per_group':1}]},9))
    write(control,'<III',options.get('ready',1),1,options.get('seq',2))
    uc.mem_write(control+64,bytes(home.encode({205060988:text})))
    write(frame+0x18,'<Q',actor)
    write(stack-12,'<I',options.get('event',205060988))
    ids={};fields={};next_mem=0x110000
    def intern(s):
        if s not in ids:ids[s]=0x7000+len(ids)
        return ids[s]
    write(actor+0x10,'<Q',cls);write(cls+0x18,'<Q',intern('BP_MenuEvCompeEventMainMenu_C')if not options.get('class')else 0x9999)
    write(cls,'<Q',vtable);write(parent,'<Q',vtable);write(vtable+0x280,'<Q',getsuper)
    # Widget lives in the superclass, not the actor's own property chain.
    def field(obj,name,value,root_class=None):
        nonlocal next_mem
        if obj not in fields:
            c=root_class or next_mem;next_mem+=0x1000
            fields[obj]={'class':c,'tail':None,'offset':0x100}
            if root_class is None:write(obj+0x10,'<Q',c)
            write(c,'<Q',vtable)
        state=fields[obj];ptr=next_mem;next_mem+=0x1000
        if state['tail'] is None:write(state['class']+0x50,'<Q',ptr)
        else:write(state['tail']+0x20,'<Q',ptr)
        off=state['offset'];state['offset']+=8;state['tail']=ptr
        write(ptr+0x28,'<Q',intern(name));write(ptr+0x4c,'<i',off);write(obj+off,'<Q',value)
        return ptr
    widget=0x180000;info=0x181000;reward=0x182000;cell1=0x183000;cell2=0x184000
    field(actor,'Widget',widget,parent)
    field(widget,'MatchMainMenuInformation',info);field(widget,'MatchMainMenuCell_1',cell1);field(widget,'MatchMainMenuCell_2',cell2)
    field(info,'MatchMainMenuReward_1',reward)
    targets=[]
    owners=(info,reward,reward,reward,cell1,cell1,cell2,cell2)
    names=('Text_Item','Text_Item','Text_Value_1','Text_Value_2','Text_Item','Text_Value','Text_Item','Text_Value')
    for i,(owner,name)in enumerate(zip(owners,names)):
        target=0x190000+i*0x1000;targets.append(target)
        ptr=field(owner,name,0 if options.get('missing')==i+1 else target)
        if options.get('bad_offset')==i+1:write(ptr+0x4c,'<i',0x10001)
    if options.get('cycle'):
        write(fields[info]['tail']+0x20,'<Q',fields[info]['tail'])
        write(fields[info]['tail']+0x28,'<Q',0x9999)
    registers={}
    for i in range(31):
        value={19:frame,29:stack}.get(i,0x700000+i*0x100)
        registers[i]=value;uc.reg_write(getattr(R,'UC_ARM64_REG_X'+str(i)),value)
    for i in range(32):uc.reg_write(getattr(R,'UC_ARM64_REG_Q'+str(i)),i*91+27)
    uc.reg_write(R.UC_ARM64_REG_SP,stack);uc.reg_write(R.UC_ARM64_REG_NZCV,0xa0000000)
    results={};stopped=[];services=[]
    def hook(uc,at,size,_):
        if at==namefn:
            pointer,count,_=struct.unpack('<QII',uc.mem_read(uc.reg_read(R.UC_ARM64_REG_X0),16))
            s=bytes(uc.mem_read(pointer,count*2)).decode('utf-16le').rstrip('\0')
            uc.reg_write(R.UC_ARM64_REG_X0,intern(s));services.append('fname')
        elif at==getsuper:
            c=uc.reg_read(R.UC_ARM64_REG_X0)
            uc.reg_write(R.UC_ARM64_REG_X0,parent if c==cls else 0);services.append('super')
        elif at==setstr:
            pointer,count,cap=struct.unpack('<QII',uc.mem_read(uc.reg_read(R.UC_ARM64_REG_X1),16))
            assert 0<count==cap<=128;assert uc.reg_read(R.UC_ARM64_REG_W2)==0
            results[uc.reg_read(R.UC_ARM64_REG_X0)]=bytes(uc.mem_read(pointer,count*2)).decode('utf-16le').rstrip('\0')
            # Engine service calls are allowed to clobber volatile registers.
            for i in range(18):uc.reg_write(getattr(R,'UC_ARM64_REG_X'+str(i)),0x900000+i)
            for i in range(8):uc.reg_write(getattr(R,'UC_ARM64_REG_Q'+str(i)),0)
            uc.reg_write(R.UC_ARM64_REG_NZCV,0)
        elif at==resume:stopped.append(True);uc.emu_stop();return
        else:return
        uc.reg_write(R.UC_ARM64_REG_PC,uc.reg_read(R.UC_ARM64_REG_X30))
    uc.hook_add(UC_HOOK_CODE,hook);uc.emu_start(code,code+len(body),count=100000)
    assert stopped and uc.reg_read(R.UC_ARM64_REG_SP)==stack
    for i,value in registers.items():
        if i==16:continue
        assert uc.reg_read(getattr(R,'UC_ARM64_REG_X'+str(i)))==(stack+16 if i==0 else value),('register',i)
    for i in range(32):assert uc.reg_read(getattr(R,'UC_ARM64_REG_Q'+str(i)))==i*91+27
    assert uc.reg_read(R.UC_ARM64_REG_NZCV)==0xa0000000
    if results:
        assert struct.unpack('<II',uc.mem_read(control+32,8))==(options.get('event',205060988),1)
    else:
        assert struct.unpack('<I',uc.mem_read(control+36,4))[0]==0
    return results,{targets[i]:text[key]for i,key in enumerate(home.TEXTS)},services


class NativeHomeTests(unittest.TestCase):
    def test_actual_emitted_code_fills_all_eight_widgets_and_restores_context(self):
        result,wanted,calls=native_probe({});self.assertEqual(result,wanted);self.assertIn('super',calls)
    def test_other_events_classes_and_incomplete_snapshots_are_untouched(self):
        for options in ({'ready':0},{'seq':3},{'event':1120005},{'class':'other'}):
            with self.subTest(options=options):self.assertEqual(native_probe(options)[0],{})
    def test_missing_or_invalid_property_does_not_partially_apply_and_cycles_are_bounded(self):
        for options in ({'missing':7},{'bad_offset':5},{'cycle':True}):
            with self.subTest(options=options):self.assertEqual(native_probe(options)[0],{})

    def test_all_reinforcement_cards_use_projected_rental_club_without_changing_native_records(self):
        from tournament_rewards import catalogue
        for row in catalogue()['cards']:
            with self.subTest(card=row['card_id']):
                self.assertEqual(emblem_probe(cid=row['card_id']),102)

    def test_owned_cards_other_previews_and_incomplete_tables_keep_original_emblem(self):
        from tournament_rewards import catalogue
        cid=catalogue()['cards'][0]['card_id']
        for options in ({'serial':7},{'discriminator':1},{'club':0},{'club':108},
                        {'cid':17},{'ready':0},{'seq':3},{'count':119},{'publish_race':True}):
            with self.subTest(options=options):self.assertEqual(emblem_probe(**dict({'cid':cid},**options)),44)
        self.assertEqual(emblem_probe(cid=cid,national=False),102)


@lru_cache(maxsize=1)
def original_engine():
    path=Path(__file__).resolve().parents[2]/'.work/xi-v17-gameplay-compare/v17-engine.so'
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
    return raw


def emblem_probe(cid,serial=0,discriminator=0,club=102,national=True,ready=1,seq=2,count=None,publish_race=False):
    """Original getter/epilogue + packaged wrapper; only table lookup is a fixture."""
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    import unicorn.arm64_const as R
    from tournament_rewards import catalogue
    profile=json.loads(PROFILE.read_text('utf8'));body=bytearray.fromhex(profile['body_hex'])
    entry=next(e for e in profile['extra_entries']if e['name']=='tournament_rental_card_emblem')
    code,control,stack,tls,player,stop=0x200000,0x300000,0x400000,0x500000,0x600000,0x700000
    for at,target in profile['absolute_fixups']:struct.pack_into('<Q',body,at,target)
    for at,size in profile['writable_fixups']:struct.pack_into('<Q',body,at,control)
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for at,size in ((0x7a87000,0x2000),(code,0x10000),(control,0x30000),(stack,0x10000),(tls,4096),(player,4096),(stop,4096)):
        uc.mem_map(at,size)
    raw=original_engine();uc.mem_write(0x7a88000,raw[0x7a84000:0x7a85000])
    uc.mem_write(code,bytes(body));texts={key:''for key in home.TEXTS}
    texts.update(rental_team_id=102,rental_emblem_ids=[r['card_id']for r in catalogue()['cards']])
    uc.mem_write(control+64,bytes(home.encode({205060988:texts})))
    uc.mem_write(control,struct.pack('<III',ready,1,seq))
    if count is not None:uc.mem_write(control+64+8,struct.pack('<I',count))
    uc.mem_write(player,struct.pack('<IIQQ',discriminator,0,cid,serial))
    uc.mem_write(player+0xd8,struct.pack('<II',club,44))
    before=bytes(uc.mem_read(player,4096))
    uc.reg_write(R.UC_ARM64_REG_X0,player);uc.reg_write(R.UC_ARM64_REG_X30,stop)
    uc.reg_write(R.UC_ARM64_REG_SP,stack+0xf000);uc.reg_write(R.UC_ARM64_REG_TPIDR_EL0,tls)
    def hook(u,address,size,_):
        if address==0x7a87f44:
            dest=u.reg_read(R.UC_ARM64_REG_X8)
            u.mem_write(dest+0x198,struct.pack('<Q',(1<<53)if national else 0))
            u.reg_write(R.UC_ARM64_REG_PC,u.reg_read(R.UC_ARM64_REG_X30))
        elif address==entry['address']:
            u.reg_write(R.UC_ARM64_REG_PC,code+entry['entry_offset'])
    uc.hook_add(UC_HOOK_CODE,hook)
    # Force a writer race precisely after allowlist lookup and before seq check.
    if publish_race:
        from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
        offset=entry['entry_offset']
        barriers=[i.address for i in Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(bytes(body[offset:]),code+offset)
                  if i.mnemonic=='dmb']
        def race(u,address,size,_):
            if address==barriers[0]:u.mem_write(control+8,struct.pack('<I',4))
        uc.hook_add(UC_HOOK_CODE,race)
    uc.emu_start(0x7a88370,stop,count=20000)
    assert bytes(uc.mem_read(player,4096))==before
    assert uc.reg_read(R.UC_ARM64_REG_SP)==stack+0xf000
    return uc.reg_read(R.UC_ARM64_REG_X0)


if __name__=='__main__':unittest.main()
