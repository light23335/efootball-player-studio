from pathlib import Path
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apk_format import replace_entries,local_signer,sign_v2,verify_v2
from compile_cache import CompileCache,clear
from export_payload import FilePayload,verified_engine,verify_replacements,extract
from movie_package import merge,MEMBER
from private_card_motion import write_movie_pak,read_movie_pak


class ExportIOTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def source(self,inner=None):
        path=self.root/('source-'+str(len(list(self.root.glob('source-*'))))+'.apk')
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED)as z:
            z.writestr('lib/arm64-v8a/libUE4.so',bytes(range(256))*10000)
            z.writestr('assets/keep.txt',b'keep')
            z.writestr('assets/test.ucas',b'old')
            if inner is not None:z.writestr(MEMBER,inner)
        return path

    def inner(self,movies=None,extra=b'unchanged'):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED)as z:
            z.comment=b'nested comment';z.writestr('keep.txt',extra*200)
            if movies:
                path=self.root/'fixture.pak';path.unlink(missing_ok=True);write_movie_pak(path,movies)
                z.writestr('PesMobile/Content/Paks/cardstudio_content_100_P.pak',path.read_bytes())
        return buffer.getvalue()

    def test_engine_extracted_once_with_complete_hash_and_arbitrary_seek_checks(self):
        raw=bytes(range(256))*10000;source=self.source()
        with zipfile.ZipFile(source)as z,patch.object(z,'open',wraps=z.open)as opened:
            engine=verified_engine(z,self.root,hashlib.sha256(raw).hexdigest())
            for offset in(2000000,10,1000000,0):
                with engine.open()as f:f.seek(offset);self.assertEqual(f.read(64),raw[offset:offset+64])
            self.assertEqual(opened.call_count,1)
        self.assertEqual(source.read_bytes()[:2],b'PK')

    def test_engine_mismatch_and_zip_corruption_remain_hard_failures(self):
        source=self.source()
        with zipfile.ZipFile(source)as z:
            with self.assertRaisesRegex(ValueError,'指纹'):verified_engine(z,self.root,'0'*64)
        self.assertFalse((self.root/'verified-libUE4.so').exists())
        with zipfile.ZipFile(source)as z:
            info=z.getinfo('lib/arm64-v8a/libUE4.so')
        with source.open('r+b')as f:
            f.seek(info.header_offset+26);n,e=struct.unpack('<HH',f.read(4));f.seek(info.header_offset+30+n+e+50)
            raw=f.read(1);f.seek(-1,1);f.write(bytes([raw[0]^1]))
        with zipfile.ZipFile(source)as z:
            with self.assertRaises(Exception):verified_engine(z,self.root,hashlib.sha256(bytes(range(256))*10000).hexdigest())
        self.assertFalse((self.root/'verified-libUE4.so').exists())

    def test_exclusive_extract_never_deletes_an_existing_file(self):
        path=self.root/'keep';path.write_bytes(b'keep')
        with zipfile.ZipFile(self.source())as z:
            with self.assertRaises(FileExistsError):extract(z,'assets/keep.txt',path)
        self.assertEqual(path.read_bytes(),b'keep')

    def test_file_payloads_stored_and_deflated_match_bytes_and_signatures(self):
        source=self.source();raw=bytes(range(251))*10000;file=self.root/'large';file.write_bytes(raw)
        key,cert=local_signer(self.root/'signing')
        for stored in(False,True):
            expected=self.root/f'bytes-{stored}.apk';actual=self.root/f'file-{stored}.apk'
            a=replace_entries(source,expected,{'assets/test.ucas':raw,'assets/new.bin':raw},store_ucas=stored,prepare_signing=True)
            b=replace_entries(source,actual,{'assets/test.ucas':FilePayload.from_path(file),'assets/new.bin':file},store_ucas=stored,prepare_signing=True)
            self.assertEqual(expected.read_bytes(),actual.read_bytes())
            signed=self.root/f'signed-{stored}.apk';sign_v2(actual,signed,key,cert,prepared=b,consume=True)
            self.assertTrue(verify_v2(signed)['verified_v2'])
            with zipfile.ZipFile(signed)as z,patch.object(z,'read',side_effect=AssertionError('Whole entry read')):
                verify_replacements(z,{'assets/test.ucas':FilePayload.from_path(file),'assets/new.bin':file})

    def test_changed_file_payload_rejected_instead_of_signing_stale_metadata(self):
        file=self.root/'payload';file.write_bytes(b'before');value=FilePayload.from_path(file);file.write_bytes(b'after!')
        with self.assertRaisesRegex(ValueError,'变化'):replace_entries(self.source(),self.root/'bad.apk',{'assets/new':value})

    def test_large_replacement_reads_are_bounded_and_readback_rejects_wrong_content(self):
        file=self.root/'large'
        with file.open('wb')as f:
            for _ in range(24):f.write(b'x'*1024**2)
        value=FilePayload.from_path(file);target=self.root/'large.apk'
        with patch.object(Path,'read_bytes',side_effect=AssertionError('Whole file read')):
            replace_entries(self.source(),target,{'assets/test.ucas':value},store_ucas=True)
            with zipfile.ZipFile(target)as z,patch.object(z,'read',side_effect=AssertionError('Whole entry read')):
                verify_replacements(z,{'assets/test.ucas':value})
        wrong=self.root/'wrong';wrong.write_bytes(b'z'*value.bytes)
        with zipfile.ZipFile(target)as z:
            with self.assertRaisesRegex(ValueError,'校验失败'):verify_replacements(z,{'assets/test.ucas':FilePayload.from_path(wrong)})

    def test_file_cache_hits_invalidates_and_recovers_corruption(self):
        cache=CompileCache(self.root/'cache',{'compiler':'v1'});calls=[]
        def produce(path):calls.append(1);path.write_bytes(b'artifact'*10000)
        first,a=cache.run_file('movie-package',{'source':'a'},produce,self.root/'one')
        second,b=cache.run_file('movie-package',{'source':'a'},produce,self.root/'two')
        self.assertFalse(a['hit']);self.assertTrue(b['hit']);self.assertEqual(len(calls),1)
        self.assertEqual(first.sha256,second.sha256)
        _,c=cache.run_file('movie-package',{'source':'b'},produce,self.root/'three');self.assertFalse(c['hit'])
        bad=cache.root/('movie-package-'+a['key']+'.zip');bad.write_bytes(b'broken')
        restored,d=cache.run_file('movie-package',{'source':'a'},produce,self.root/'four')
        self.assertFalse(d['hit']);self.assertEqual(restored.sha256,first.sha256);self.assertEqual(cache.stats['corrupt'],1)
        different=CompileCache(cache.root,{'compiler':'v2'})
        _,e=different.run_file('movie-package',{'source':'a'},produce,self.root/'five');self.assertFalse(e['hit'])
        self.assertGreater(clear(cache.root)['files'],0)

    def test_file_cache_checks_payload_digest_and_respects_storage_budget(self):
        cache=CompileCache(self.root/'cache',{},limit=9000)
        def produce(path):path.write_bytes(b'content')
        one,info=cache.run_file('movie-package',{},produce,self.root/'one')
        target=cache.root/('movie-package-'+info['key']+'.zip')
        with zipfile.ZipFile(target)as z:manifest=json.loads(z.read('manifest.json'))
        with zipfile.ZipFile(target,'w')as z:
            z.writestr('manifest.json',json.dumps(manifest));z.writestr('payload',b'corrupt')
        two,info=cache.run_file('movie-package',{},produce,self.root/'two')
        self.assertFalse(info['hit']);self.assertEqual(one.sha256,two.sha256)
        cache.run_file('movie-package',{'large':True},lambda p:p.write_bytes(b'x'*10000)and None,self.root/'large')
        self.assertLessEqual(sum(p.stat().st_size for p in cache.root.glob('*.zip')),cache.limit)

    def test_movie_merge_cache_and_source_changes_preserve_unrelated_compressed_data(self):
        movies={'PlayerCard/0500_317_m02_v.usm':b'CRID-test-video'}
        source=self.source(self.inner());cache=CompileCache(self.root/'cache',{});self.addCleanup(cache.close)
        outputs=[]
        for i in range(2):
            work=self.root/str(i);work.mkdir()
            with zipfile.ZipFile(source)as z:
                with patch('private_card_motion.write_movie_pak',side_effect=AssertionError('Cache miss'))if i else patch('private_card_motion.write_movie_pak',wraps=write_movie_pak):
                    value,report=merge(z,None,{},movies,work,cache)
            self.assertEqual(report['hit'],bool(i));outputs.append(value)
        self.assertEqual(outputs[0].sha256,outputs[1].sha256)
        with zipfile.ZipFile(outputs[0].path)as z:
            self.assertEqual(z.comment,b'nested comment');self.assertEqual(z.read('keep.txt'),b'unchanged'*200)
            self.assertEqual(read_movie_pak(z.read('PesMobile/Content/Paks/cardstudio_content_100_P.pak'),True),movies)
        different=self.source(self.inner(extra=b'new baseline'));work=self.root/'different';work.mkdir()
        with zipfile.ZipFile(different)as z:_,report=merge(z,None,{},movies,work,cache)
        self.assertFalse(report['hit'])

    def test_unchanged_movies_reuse_exact_source_and_conflicts_still_fail(self):
        movies={'PlayerCard/0500_317_m02_v.usm':b'CRID-test-video'}
        original=self.inner(movies);source=self.source(original);work=self.root/'work';work.mkdir()
        with zipfile.ZipFile(source)as z,patch('apk_format.replace_entries',side_effect=AssertionError('Unneeded rewrite')):
            value,report=merge(z,None,{},movies,work)
        self.assertTrue(report['source_reused']);self.assertEqual(value.sha256,hashlib.sha256(original).hexdigest())
        work=self.root/'conflict';work.mkdir()
        with zipfile.ZipFile(source)as z:
            with self.assertRaisesRegex(ValueError,'冲突'):merge(z,None,{},dict.fromkeys(movies,b'CRID-different'),work)

    def test_coach_modified_movie_baseline_is_kept_and_not_replaced_with_source_apk(self):
        source=self.source(self.inner(extra=b'old'));existing=self.root/'coach.zip';existing.write_bytes(self.inner(extra=b'coach'))
        work=self.root/'work';work.mkdir()
        with zipfile.ZipFile(source)as z:
            result,_=merge(z,FilePayload.from_path(existing),{}, {'PlayerCard/0500_317_m02_v.usm':b'CRID-video'},work)
        with zipfile.ZipFile(result.path)as z:self.assertEqual(z.read('keep.txt'),b'coach'*200)


if __name__=='__main__':unittest.main()
