"""Published-version recovery and real shared allocator/file-lock regressions."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import copy,json,os,subprocess,sys,tempfile,types,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_live import (PUBLISHED_VERSION_FLOOR as FLOOR,VERSION_LIMIT,
                         _reserve,reserve_shared,library_version)

def template(version):return {'version_file':{'version':version}}
def registry(last,**hashes):return {'V17':{'last':last,'hashes':hashes}}

class NativeLiveVersionTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parents[2]/'.work/live-version-fix-20261106/unit-temp'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def test_actual_2491_cache_2489_export_is_reallocated_and_repeat_is_stable(self):
        self.assertGreaterEqual(FLOOR,2026102491)
        stale=registry(2026102489,changed_cpk=2026102489)
        version,state=_reserve(stale,'V17',template(2026102488),'changed_cpk',observed_versions=(2026102402,))
        self.assertEqual(version,FLOOR+1);self.assertGreater(version,2026102491)
        repeat,_=_reserve(state,'V17',template(2026102488),'changed_cpk',observed_versions=(2026102402,))
        self.assertEqual(repeat,version)
    def test_clean_share_has_floor_without_any_registry_or_export_history(self):
        version,_=_reserve({},'V17',template(2026102488),'new',observed_versions=(2026102402,))
        self.assertEqual(version,FLOOR+1)
    def test_known_same_fingerprint_at_published_floor_can_still_be_reused(self):
        version,_=_reserve(registry(FLOOR,same=FLOOR),'V17',template(FLOOR-3),'same')
        self.assertEqual(version,FLOOR)
    def test_source_and_current_library_can_each_raise_the_floor(self):
        for source,library in((FLOOR+8,FLOOR-2),(FLOOR-2,FLOOR+8)):
            with self.subTest(source=source,library=library):
                version,state=_reserve({},'V17',template(source),'new',observed_versions=(library,))
                self.assertEqual(version,FLOOR+9)
                self.assertEqual(_reserve(state,'V17',template(source),'new',observed_versions=(library,))[0],version)
    def test_same_as_source_must_advance_even_with_a_known_fingerprint(self):
        version,_=_reserve(registry(FLOOR+5,same=FLOOR+5),'V17',template(FLOOR+5),'same')
        self.assertEqual(version,FLOOR+6)
    def test_hash_version_gap_is_part_of_maximum_and_is_repaired_on_reuse(self):
        high=FLOOR+12
        version,state=_reserve(registry(FLOOR,known=high),'V17',template(FLOOR-1),'known')
        self.assertEqual(version,high);self.assertEqual(state['V17']['last'],high)
        changed,_=_reserve(registry(FLOOR,known=high),'V17',template(FLOOR-1),'new')
        self.assertEqual(changed,high+1)
    def test_all_release_groups_and_seed_hashes_participate(self):
        shared=self.root/'shared.json';local=self.root/'local.json';seed=self.root/'seed.json'
        shared.write_text(json.dumps(registry(FLOOR+1,shared=FLOOR+1)))
        local.write_text(json.dumps({'older-release':{'last':FLOOR,'hashes':{'hidden':FLOOR+7}}}))
        seed.write_text(json.dumps({'V14':{'last':FLOOR+2,'hashes':{'gap':FLOOR+9}}}))
        before=local.read_bytes(),seed.read_bytes()
        version,_=reserve_shared(shared,local,'V17',template(FLOOR-3),'new',(seed,))
        self.assertEqual(version,FLOOR+10)
        self.assertEqual((local.read_bytes(),seed.read_bytes()),before)
        self.assertEqual(json.loads(shared.read_text())['V17']['last'],version)
    def test_threaded_versions_never_regress_or_collide_across_releases(self):
        shared=self.root/'shared.json';local=self.root/'local.json'
        def reserve(i):return reserve_shared(shared,local,'V17'if i%2 else'V14',template(FLOOR-1),str(i),observed_versions=(FLOOR+4,))[0]
        with ThreadPoolExecutor(max_workers=8)as pool:versions=list(pool.map(reserve,range(16)))
        self.assertEqual(sorted(versions),list(range(FLOOR+5,FLOOR+21)))
        self.assertFalse(list(self.root.glob('*.tmp')))
    def test_independent_processes_share_the_file_lock_and_atomic_registry(self):
        shared=self.root/'shared.json';local=self.root/'local.json';core=Path(__file__).resolve().parents[1]
        program='import sys;sys.path.insert(0,sys.argv[1]);from native_live import reserve_shared;print(reserve_shared(sys.argv[2],sys.argv[3],"V17",{"version_file":{"version":1}},sys.argv[4])[0])'
        children=[]
        for i in range(6):
            children.append(subprocess.Popen([sys.executable,'-c',program,str(core),str(shared),str(local),'process-'+str(i)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt'else 0))
        versions=[]
        for child in children:
            out,err=child.communicate(timeout=40);self.assertEqual(child.returncode,0,err);versions.append(int(out))
        self.assertEqual(sorted(versions),list(range(FLOOR+1,FLOOR+7)))
        self.assertEqual(json.loads(shared.read_text())['V17']['last'],max(versions))
    def test_invalid_source_observed_last_and_hash_versions_are_rejected(self):
        invalid=(True,False,-1,VERSION_LIMIT,VERSION_LIMIT+1,'2491',2491.5,None)
        for value in invalid:
            for kind in('source','observed','last','hash'):
                with self.subTest(value=value,kind=kind):
                    state=registry(FLOOR,old=FLOOR)
                    t=template(value if kind=='source'else FLOOR-1)
                    observed=(value,)if kind=='observed'else()
                    if kind=='last':state['V17']['last']=value
                    if kind=='hash':state['V17']['hashes']['old']=value
                    before=copy.deepcopy(state)
                    with self.assertRaises(ValueError):_reserve(state,'V17',t,'new',observed_versions=observed)
                    self.assertEqual(state,before)
    def test_overflow_keeps_registry_unchanged_but_last_valid_known_hash_reuses(self):
        state=registry(VERSION_LIMIT-2,known=VERSION_LIMIT-1);before=copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError,'范围已用完'):_reserve(state,'V17',template(FLOOR-1),'new')
        self.assertEqual(state,before)
        version,_=_reserve(state,'V17',template(FLOOR-1),'known')
        self.assertEqual(version,VERSION_LIMIT-1)
    def test_shared_overflow_does_not_replace_an_existing_registry(self):
        shared=self.root/'shared.json';local=self.root/'local.json'
        shared.write_text(json.dumps(registry(VERSION_LIMIT-1,last_valid=VERSION_LIMIT-1)))
        before=shared.read_bytes()
        with self.assertRaises(ValueError):reserve_shared(shared,local,'V17',template(FLOOR-1),'new')
        self.assertEqual(shared.read_bytes(),before);self.assertFalse(local.exists())
    def library(self,version):
        resources=self.root/'resources';resources.mkdir(exist_ok=True)
        store=types.SimpleNamespace(root=self.root/'data');store.root.mkdir(exist_ok=True)
        apk=self.root/'current-library.apk'
        with zipfile.ZipFile(apk,'w')as z:
            z.writestr('assets/gateway-release/work/templates/CMD_LOGIN_LIVEDATA.json',json.dumps(template(version)))
        (store.root/'active-game.json').write_text(json.dumps({'apk':str(apk)}))
        library=types.SimpleNamespace(home=self.root/'home',root=self.root/'cache',resources=resources,profile={'release_id':'fixture'})
        return library,store,apk
    def test_real_export_allocator_reads_current_library_apk_independently_of_source(self):
        from native_package import _reserve_live_version
        library,store,apk=self.library(FLOOR+15)
        self.assertEqual(library_version(library,store),FLOOR+15)
        version,_=_reserve_live_version(library,store,'V17',template(FLOOR-3),'new-source-content')
        self.assertEqual(version,FLOOR+16)
        repeated,_=_reserve_live_version(library,store,'V17',template(FLOOR-3),'new-source-content')
        self.assertEqual(repeated,version)
    def test_missing_current_library_is_not_silently_replaced_with_old_source(self):
        from native_package import _reserve_live_version
        library,store,apk=self.library(FLOOR+15);apk.unlink()
        with self.assertRaisesRegex(ValueError,'当前资料库主 APK'):_reserve_live_version(library,store,'V17',template(FLOOR-3),'new')
        self.assertFalse((self.root/'.player-studio-shared/native-live-versions.json').exists())

if __name__=='__main__':unittest.main()
