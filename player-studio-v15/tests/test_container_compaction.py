"""Real IoStore writes: repeated updates, indirect chunks, AES and shared blocks."""
from pathlib import Path
import hashlib,struct,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_iostore import Container,append_container,write_container,package_header,directory_index,aes


class ContainerCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.header=(100).to_bytes(8,'little')+bytes(3)+bytes([10])
        self.ids=[n.to_bytes(8,'little')+bytes(3)+bytes([2]) for n in (200,201,202)]
        self.packages=[{'id':200+i,'exports':1,'bundles':1,'imports':[]} for i in range(3)]
        self.values=[hashlib.shake_256(str(i).encode()).digest(750) for i in range(3)]
        self.source=self.root/'initial.utoc'
        write_container(self.source,[(self.header,package_header(100,self.packages)),*zip(self.ids,self.values)],
                        {'Game/live.uasset':1},100,block_size=256)

    def rewrite(self,path,encrypted=False,shared=False):
        """Construct legitimate old index layouts, including unnamed dependency chunks."""
        src=Container(path);blocks=[];key=bytes(range(32)) if encrypted else None
        binary=path.with_suffix('.ucas').read_bytes();out=bytearray()
        for block in src.blocks:
            offset=int.from_bytes(block[:5],'little');size=int.from_bytes(block[5:8],'little')
            value=binary[offset:offset+size]
            if encrypted:value=aes(value+bytes(-len(value)%16),key,True)
            blocks.append(len(out).to_bytes(5,'little')+block[5:]);out.extend(value)
        ranges=list(src.ranges);metas=bytearray(src.metas)
        if shared:
            # Third indexed chunk is an independently hashed slice in another
            # chunk's live block, without a directory entry.
            start,size=ranges[2];ranges[3]=(start+10,100)
            raw=src.read_chunk(2)[10:110];metas[3*33:4*33]=hashlib.sha1(raw).digest()+bytes(12)+bytes([0])
        directory=directory_index({p.removeprefix('../../../'):i for p,i in src.paths.items()})
        header=bytearray(src.header)
        if encrypted:header[80]|=2;directory=aes(directory+bytes(-len(directory)%16),key,True)
        struct.pack_into('<I',header,48,len(directory))
        target=self.root/('encrypted.utoc' if encrypted else 'shared.utoc')
        target.with_suffix('.ucas').write_bytes(out)
        target.write_bytes(header+b''.join(src.chunk_ids)+b''.join(a.to_bytes(5,'big')+b.to_bytes(5,'big') for a,b in ranges)
                           +b''.join(blocks)+b'Zlib'+bytes(28)+directory+metas)
        return Container(target,key)

    def test_repeated_updates_keep_all_indexed_dependencies_and_stop_growing(self):
        for encrypted in (False,True):
            source=self.rewrite(self.source,True) if encrypted else Container(self.source)
            sizes=[]
            for iteration in range(4):
                output=self.root/f'update-{encrypted}-{iteration}.utoc'
                source=append_container(source,output,[(self.ids[0],self.values[0])],{'Game/live.uasset':0},[self.packages[0]],{1})
                for index,value in enumerate(self.values):self.assertEqual(source.read_chunk(index+1),value)
                self.assertEqual(source.chunk_ids,[self.header,*self.ids])
                sizes.append(output.with_suffix('.ucas').stat().st_size)
                self.assertGreater(source.compaction_report['reclaimed_source_bytes'],0)
            self.assertEqual(len(set(sizes)),1)

    def test_shared_live_blocks_and_empty_chunks_survive(self):
        source=self.rewrite(self.source,shared=True);expected=source.read_chunk(3)
        empty=(999).to_bytes(8,'little')+bytes(3)+bytes([3])
        target=append_container(source,self.root/'shared-new.utoc',[(self.ids[0],self.values[0]),(empty,b'')],
                                {'Game/live.uasset':0},[self.packages[0]],{1})
        self.assertEqual(target.read_chunk(2),self.values[1]);self.assertEqual(target.read_chunk(3),expected)
        self.assertEqual(target.read_chunk(4),b'')
        final=append_container(target,self.root/'shared-final.utoc',[],{},[])
        self.assertEqual(final.read_chunk(3),expected);self.assertEqual(final.read_chunk(4),b'')

    def test_obsolete_unindexed_physical_garbage_is_reclaimed(self):
        with self.source.with_suffix('.ucas').open('ab') as f:f.write(bytes(4096))
        target=append_container(Container(self.source),self.root/'clean.utoc',[],{},[])
        self.assertGreaterEqual(target.compaction_report['reclaimed_source_bytes'],4096)
        for index,value in enumerate(self.values):self.assertEqual(target.read_chunk(index+1),value)

    def test_cached_compression_is_byte_identical_and_warm_exports_do_not_recompress(self):
        from compile_cache import CompileCache
        for encrypted in(False,True):
            source=self.rewrite(self.source,True)if encrypted else Container(self.source)
            cache=CompileCache(self.root/('cache-'+str(encrypted)),{})
            def build(label,use_cache):
                path=self.root/(label+'-'+str(encrypted)+'.utoc')
                return append_container(source,path,[(self.ids[0],self.values[0])],{'Game/live.uasset':0},[self.packages[0]],{1},cache=use_cache)
            expected=build('baseline',None);cold=build('cold',cache)
            with patch('native_iostore.zlib.compress',side_effect=AssertionError('Warm export recompressed data')):
                warm=build('warm',cache)
            for suffix in('.utoc','.ucas'):
                self.assertEqual(expected.path.with_suffix(suffix).read_bytes(),cold.path.with_suffix(suffix).read_bytes())
                self.assertEqual(expected.path.with_suffix(suffix).read_bytes(),warm.path.with_suffix(suffix).read_bytes())
            self.assertGreater(cache.stats['hits']['iostore'],0)
            for i,value in enumerate(self.values):self.assertEqual(warm.read_chunk(i+1),value)


if __name__=='__main__':unittest.main()
