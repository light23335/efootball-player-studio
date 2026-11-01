from pathlib import Path
import hashlib,io,json,struct,sys,tempfile,threading,unittest,zipfile,zlib
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_cpk
from native_cpk import decode_session,decode_statistics,unwrap,wrap
from native_strings import merge_all,merge_groups,merge,write,wrap as wrap_strings,read,unwrap as unwrap_strings
from export_payload import FilePayload,FileView
from compile_cache import CompileCache,clear
from movie_package import merge as merge_movies,MEMBER
from apk_format import replace_entries,local_signer,sign_v2,verify_v2

HEADER=bytes.fromhex('ff21835745535953')+bytes(8)


class ExportOptimizations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def cache(self,limit=None):
        result=CompileCache(self.root/'cache',{},limit=limit);self.addCleanup(result.close);return result

    def test_decoded_tables_share_only_within_scope_and_fresh_reads_bypass_cache(self):
        data=wrap(b'original-table'*100,HEADER)
        with patch('native_cpk._unwrap',wraps=native_cpk._unwrap)as decoder:
            with decode_session()as state:
                first=unwrap(data);self.assertEqual(unwrap(bytes(bytearray(data))),first)
                self.assertEqual(wrap(first,data),data);self.assertEqual(decoder.call_count,1)
                self.assertEqual(unwrap(data,fresh=True),first);self.assertEqual(decoder.call_count,2)
                self.assertEqual(decode_statistics()['fresh_reads'],1)
            self.assertFalse(state['cache']);self.assertEqual(decode_statistics(),{})
            with decode_session():self.assertEqual(unwrap(data),first)
            self.assertEqual(decoder.call_count,3)

    def test_decode_cache_content_identity_limits_and_exceptions(self):
        one=wrap(b'a'*300,HEADER);two=wrap(b'b'*300,HEADER)
        with decode_session(limit=360)as state:
            self.assertEqual(unwrap(one),b'a'*300);self.assertEqual(unwrap(two),b'b'*300)
            self.assertLessEqual(state['peak_bytes'],360);self.assertLessEqual(len(state['cache']),1)
            with self.assertRaises(ValueError):unwrap(b'invalid')
        with self.assertRaises(RuntimeError):
            with decode_session():unwrap(one);raise RuntimeError('abort export')
        self.assertEqual(decode_statistics(),{})

    def test_decode_cache_nested_and_parallel_exports_do_not_mix(self):
        one=wrap(b'a'*10,HEADER);two=wrap(b'b'*10,HEADER)
        with decode_session():
            unwrap(one)
            with decode_session():unwrap(two);self.assertEqual(decode_statistics()['misses'],1)
            unwrap(one);self.assertEqual(decode_statistics()['hits'],1)
        results=[]
        def run(value):
            with decode_session():
                a=unwrap(value);unwrap(value);results.append((a,decode_statistics()['misses'],decode_statistics()['hits']))
        threads=[threading.Thread(target=run,args=(value,))for value in(one,two)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(sorted(results),[(b'a'*10,1,1),(b'b'*10,1,1)])

    def test_unchanged_strings_keep_exact_wrapper_and_skip_write_compress(self):
        groups=[{'name':'SkillW','id':31,'items':{1:'Same'}}]
        raw=wrap_strings(write(groups));update=[{'name':'SkillW','id':31,'items':{1:'Same'}}]
        with patch('native_strings.write',side_effect=AssertionError('Unchanged text rebuilt')):
            self.assertIs(merge_groups(raw,update),raw)
        changed=merge_groups(raw,[{'name':'SkillW','id':31,'items':{1:'Changed'}}])
        self.assertEqual(read(unwrap_strings(changed))[0]['items'][1],'Changed')

    def test_booster_and_skill_texts_parse_once_and_collision_checks_remain(self):
        groups=[{'name':'Any3W','id':1142,'items':{60000:'Booster'}},{'name':'SkillW','id':31,'items':{1:'Name'}}]
        raw=wrap_strings(write(groups));updates=[{'name':'SkillW','id':31,'items':{1:'New'}}]
        with patch('native_strings.read',wraps=read)as parser:
            value=merge_all(raw,{60000:'Booster'},{60000},[{'name':'SkillW','id':31,'items':{1:'Name'}}])
            self.assertIs(value,raw);self.assertEqual(parser.call_count,1)
        new=merge_all(raw,{60000:'New booster'},{60000},updates)
        parsed=read(unwrap_strings(new));self.assertEqual(parsed[0]['items'][60000],'New booster')
        self.assertEqual(parsed[1]['items'][1],'New')
        with self.assertRaisesRegex(ValueError,'占用'):merge(raw,{60000:'Booster'})
        with self.assertRaises(ValueError):merge_groups(raw,[{'name':'Wrong','id':31,'items':{1:'Same'}}])
        with self.assertRaises(ValueError):merge_groups(b'bad',[])

    def test_equal_cpk_replacements_are_deflated_once_with_identical_encoded_bytes(self):
        source=self.root/'source.apk';raw=b'cpk fixture'*100000
        with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED)as z:
            for name in('assets/active.cpk','assets/download.cpk'):z.writestr(name,b'old')
        path=self.root/'data.cpk';path.write_bytes(raw);output=self.root/'output.apk'
        with patch('apk_format.zlib.compressobj',wraps=zlib.compressobj)as encoder:
            report=replace_entries(source,output,{'assets/active.cpk':raw,'assets/download.cpk':FilePayload.from_path(path)},prepare_signing=True)
            self.assertEqual(encoder.call_count,1)
        self.assertEqual(report['compaction']['deflate_reuse']['reused_entries'],1)
        self.assertEqual(report['compaction']['deflate_reuse']['uncompressed_bytes_not_reencoded'],len(raw))
        def encoded(name):
            with zipfile.ZipFile(output)as z:info=z.getinfo(name)
            with output.open('rb')as f:
                f.seek(info.header_offset+26);n,e=struct.unpack('<HH',f.read(4));f.seek(info.header_offset+30+n+e);return f.read(info.compress_size)
        self.assertEqual(encoded('assets/active.cpk'),encoded('assets/download.cpk'))
        with zipfile.ZipFile(output)as z:self.assertEqual(z.read('assets/download.cpk'),raw)
        key,cert=local_signer(self.root/'signing');signed=self.root/'signed.apk'
        sign_v2(output,signed,key,cert,prepared=report,consume=True);self.assertTrue(verify_v2(signed)['verified_v2'])

    def test_different_payloads_are_not_reused_as_one_compression(self):
        source=self.root/'source.apk'
        with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED)as z:
            z.writestr('a',b'old');z.writestr('b',b'old')
        result=replace_entries(source,self.root/'new.apk',{'a':b'first','b':b'second'})
        self.assertEqual(result['compaction']['deflate_reuse']['reused_entries'],0)

    def test_stored_zip_payload_is_bounded_and_outer_zip_can_be_rewritten_from_view(self):
        inner=io.BytesIO()
        with zipfile.ZipFile(inner,'w')as z:z.writestr('keep',b'kept');z.writestr('change',b'old')
        source=self.root/'source.apk'
        with zipfile.ZipFile(source,'w')as z:z.writestr('before',b'prefix');z.writestr(MEMBER,inner.getvalue());z.writestr('after',b'suffix')
        with zipfile.ZipFile(source)as z:value=FilePayload.from_zip(z,MEMBER)
        self.assertGreater(value.offset,0)
        with value.open()as stream:
            stream.seek(-10,2);self.assertEqual(len(stream.read(100)),10)
            stream.seek(0);self.assertEqual(stream.read(),inner.getvalue())
        output=self.root/'new-inner.zip';replace_entries(value,output,{'change':b'new'})
        with zipfile.ZipFile(output)as z:self.assertEqual(z.read('keep'),b'kept');self.assertEqual(z.read('change'),b'new')

    def test_direct_cache_hit_writes_no_output_and_is_pinned_until_export_finishes(self):
        cache=self.cache();calls=[]
        def build(path):calls.append(1);path.write_bytes(b'artifact'*10000)
        original,_=cache.run_file('movie-package',{},build,self.root/'one',direct=True)
        hit,info=cache.run_file('movie-package',{},build,self.root/'two',direct=True)
        self.assertTrue(info['hit']);self.assertEqual(calls,[1]);self.assertFalse((self.root/'two').exists())
        self.assertIsNotNone(hit.lease);self.assertGreater(hit.offset,0)
        self.assertEqual(clear(cache.root)['files'],0)
        buffer=io.BytesIO();hit.copy_to(buffer);self.assertEqual(buffer.getvalue(),b'artifact'*10000)
        cache.close();self.assertEqual(clear(cache.root)['files'],1)
        with self.assertRaises(ValueError):hit.copy_to(io.BytesIO())

    def test_direct_cache_corruption_rebuilds_instead_of_using_manifest_as_evidence(self):
        cache=self.cache();calls=[]
        def build(path):calls.append(1);path.write_bytes(b'correct')
        _,info=cache.run_file('movie-package',{},build,self.root/'one',direct=True)
        target=cache.root/('movie-package-'+info['key']+'.zip')
        with zipfile.ZipFile(target)as z:manifest=z.read('manifest.json')
        with zipfile.ZipFile(target,'w')as z:z.writestr('payload',b'corrupt');z.writestr('manifest.json',manifest)
        value,result=cache.run_file('movie-package',{},build,self.root/'two',direct=True)
        self.assertFalse(result['hit']);self.assertEqual(calls,[1,1]);self.assertEqual(value.sha256,hashlib.sha256(b'correct').hexdigest())

    def test_movie_budget_preserves_artwork_cache(self):
        cache=self.cache(64*1024)
        cache.run('card',{},lambda:b'a'*20000,encoded=True)
        for n in range(3):cache.run_file('movie-package',{'n':n},lambda p:p.write_bytes(b'x'*20000)and None,self.root/str(n),direct=True)
        self.assertEqual(len(list(cache.root.glob('card-*.zip'))),1)
        self.assertLessEqual(sum(p.stat().st_size for p in cache.root.glob('movie-package-*.zip')),cache.limit//2)

    def test_video_hit_and_unchanged_source_leave_no_intermediate_movie_files(self):
        empty=io.BytesIO()
        with zipfile.ZipFile(empty,'w')as z:z.writestr('keep',b'keep')
        source=self.root/'source.apk'
        with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED)as z:z.writestr(MEMBER,empty.getvalue())
        cache=self.cache();movies={'PlayerCard/0500_317_m02_v.usm':b'CRID-video'}
        for n in range(2):
            work=self.root/str(n);work.mkdir()
            with zipfile.ZipFile(source)as z:
                with patch('private_card_motion.read_movie_pak',side_effect=AssertionError('Cached movie parsed again'))if n else patch('private_card_motion.read_movie_pak',wraps=__import__('private_card_motion').read_movie_pak):
                    result,report=merge_movies(z,None,{},movies,work,cache)
            if n:
                self.assertTrue(report['direct_cache_view']);self.assertEqual(list(work.iterdir()),[])
                self.assertEqual(report['baseline_temp_bytes']+report['result_temp_bytes'],0)
            else:
                self.assertGreater(report['baseline_temp_bytes'],0)
                self.assertTrue((work/'movie-source-miss.zip').is_file())
        updated=result
        # The generated inner archive is already complete; reuse the chosen
        # baseline verbatim, even if it is a file interval in a cache archive.
        work=self.root/'complete';work.mkdir()
        with zipfile.ZipFile(source)as z:value,report=merge_movies(z,updated,{},movies,work)
        self.assertTrue(report['source_reused']);self.assertEqual(value.sha256,updated.sha256)
        self.assertEqual(list(work.iterdir()),[])

    def test_combined_final_validation_reads_each_actual_cpk_and_control_file_once(self):
        from test_live_data import LiveDataTests
        from native_live import verify_apk
        fixture=LiveDataTests().apk()
        with zipfile.ZipFile(fixture)as z:expected={n:z.read(n)for n in z.namelist()}
        fixture.seek(0);counts={};original=zipfile.ZipFile.open
        def tracked(archive,name,*args,**kwargs):
            key=name.filename if isinstance(name,zipfile.ZipInfo)else name;counts[key]=counts.get(key,0)+1
            return original(archive,name,*args,**kwargs)
        with patch.object(zipfile.ZipFile,'open',tracked):result=verify_apk(fixture,expected)
        self.assertTrue(result['verified']);self.assertEqual(result['additional_digest_reads'],0)
        self.assertGreater(result['shared_actual_digests'],0);self.assertTrue(all(n==1 for n in counts.values()))
        for change in({'download':b'wrong'},{'old_template':True},{'old_document':True},{'old_manifest':True}):
            bad=LiveDataTests().apk(**change)
            with zipfile.ZipFile(bad)as z:bad_expected={n:z.read(n)for n in z.namelist()}
            bad.seek(0)
            with self.assertRaises(ValueError):verify_apk(bad,bad_expected)


if __name__=='__main__':unittest.main()
