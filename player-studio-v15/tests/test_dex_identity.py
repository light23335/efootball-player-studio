from pathlib import Path
import hashlib,json,struct,sys,tempfile,unittest,zipfile,zlib
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dex_identity import rewrite,inspect
from apk_installation import ALIASES
from apk_installation import COEXIST_GAME,COEXIST_RESOURCES,coexist_entries,resources_needed,remember_resource,local_certificate
from install_pairs import check,validate_install


def leb(value):
    out=bytearray()
    while value>=128:out.append((value&127)|128);value>>=7
    out.append(value);return bytes(out)


def strings(raw):
    n,at=struct.unpack_from('<II',raw,56);result=[]
    for i in range(n):
        pos=struct.unpack_from('<I',raw,at+i*4)[0]
        while raw[pos]&128:pos+=1
        pos+=1;result.append(raw[pos:raw.index(0,pos)].decode())
    return result


def fixture():
    values=sorted(['I','LExample;','Ljava/lang/Object;','V','Example.java','field','method',
                   'com.efootball.revival.local','com.efootball.revival.resources.files','sig'])
    ids={s:i for i,s in enumerate(values)};raw=bytearray(112);raw[:8]=b'dex\n039\0';maps=[(0,1,0)]
    def section(kind,count,size):
        raw.extend(bytes((-len(raw))%4));at=len(raw);maps.append((kind,count,at));raw.extend(bytes(size));return at
    st=section(1,len(values),4*len(values));types=section(2,4,16);proto=section(3,1,12);fields=section(4,1,8);methods=section(5,1,8);classes=section(6,1,32)
    for i,s in enumerate(('I','LExample;','Ljava/lang/Object;','V')):struct.pack_into('<I',raw,types+i*4,ids[s])
    struct.pack_into('<III',raw,proto,ids['V'],3,0);struct.pack_into('<HHI',raw,fields,1,0,ids['field']);struct.pack_into('<HHI',raw,methods,1,0,ids['method'])
    struct.pack_into('<8I',raw,classes,1,1,2,0,ids['com.efootball.revival.local'],0,0,0)
    a=ids['com.efootball.revival.local'];b=ids['com.efootball.revival.resources.files']
    instructions=[0x0017,0x017f,0x001a,0x001a,a,0x001b,b,0,0x000e,0,0x0300,2,3,0,0x001a,0x001b,0]
    code=section(0x2001,1,16+2*len(instructions));struct.pack_into('<HHHHII',raw,code,2,0,0,0,0,len(instructions));struct.pack_into('<'+'H'*len(instructions),raw,code+16,*instructions)
    debug=len(raw);maps.append((0x2003,1,debug));raw.extend(leb(1)+leb(1)+leb(a+1)+bytes([4])+leb(0)+leb(b+1)+leb(0)+leb(a+1)+bytes([9])+leb(b+1)+bytes([0]));struct.pack_into('<I',raw,code+8,debug)
    annotation=len(raw);maps.append((0x2004,1,annotation));raw.extend(bytes([1])+leb(1)+leb(1)+leb(ids['field'])+bytes([0x17,b]))
    array=len(raw);maps.append((0x2005,1,array));raw.extend(leb(2)+bytes([0x17,a,0x1c])+leb(1)+bytes([0x17,b]))
    data_strings=len(raw);maps.append((0x2002,len(values),data_strings))
    for i,s in enumerate(values):struct.pack_into('<I',raw,st+i*4,len(raw));raw.extend(leb(len(s))+s.encode()+b'\0')
    raw.extend(bytes((-len(raw))%4));map_at=len(raw);maps.append((0x1000,1,map_at));raw.extend(struct.pack('<I',len(maps)))
    for kind,count,at in maps:raw.extend(struct.pack('<HHII',kind,0,count,at))
    struct.pack_into('<III',raw,32,len(raw),112,0x12345678);struct.pack_into('<I',raw,52,map_at)
    for header,count,at in ((56,len(values),st),(64,4,types),(72,1,proto),(80,1,fields),(88,1,methods),(96,1,classes)):struct.pack_into('<II',raw,header,count,at)
    struct.pack_into('<II',raw,104,len(raw)-code,code);raw[12:32]=hashlib.sha1(raw[32:]).digest();struct.pack_into('<I',raw,8,zlib.adler32(raw[12:])&0xffffffff)
    return bytes(raw),{'code':code,'source':classes+16,'debug':debug,'annotation':annotation,'array':array}


class DexIdentityTests(unittest.TestCase):
    def test_reordered_constants_keep_code_debug_annotation_and_array_values(self):
        raw,p=fixture();before=strings(raw);after,count=rewrite(raw,ALIASES);names=strings(after)
        self.assertEqual(count,2);self.assertEqual(len(after),len(raw));self.assertEqual(names,sorted(names));inspect(after)
        def renamed(s):
            for a,b in ALIASES.items():s=s.replace(a,b)
            return s
        for at,width in ((p['source'],4),(p['code']+24,2),(p['code']+28,4)):
            self.assertEqual(names[int.from_bytes(after[at:at+width],'little')],renamed(before[int.from_bytes(raw[at:at+width],'little')]))
        for at in (p['debug']+2,p['debug']+5,p['debug']+7,p['debug']+9):
            self.assertEqual(names[after[at]-1],renamed(before[raw[at]-1]))
        for at in (p['annotation']+5,p['array']+2,p['array']+6):self.assertEqual(names[after[at]],renamed(before[raw[at]]))
        self.assertEqual(after[p['code']+16:p['code']+22],raw[p['code']+16:p['code']+22])
        self.assertEqual(after[p['code']+36:p['code']+50],raw[p['code']+36:p['code']+50])
        self.assertEqual(rewrite(after,ALIASES),(after,0))

    def test_repair_legacy_unsorted_byte_replacement_without_renaming_again(self):
        raw,_=fixture();old=bytearray(raw)
        for a,b in ALIASES.items():old=old.replace(a.encode(),b.encode())
        old[12:32]=hashlib.sha1(old[32:]).digest();struct.pack_into('<I',old,8,zlib.adler32(old[12:])&0xffffffff)
        with self.assertRaisesRegex(ValueError,'排序'):inspect(old)
        repaired,count=rewrite(old,{})
        self.assertEqual(count,0);self.assertEqual(repaired,rewrite(raw,ALIASES)[0]);inspect(repaired)

    def test_unchanged_dex_is_byte_identical_and_corruption_is_rejected(self):
        raw,_=fixture();self.assertEqual(rewrite(raw,{}),(raw,0))
        bad=bytearray(raw);bad[-1]^=1
        with self.assertRaisesRegex(ValueError,'校验和'):rewrite(bad,{})

    def test_update_repairs_an_already_renamed_resource_without_changing_its_identity(self):
        raw,_=fixture();old=bytearray(raw)
        for a,b in ALIASES.items():old=old.replace(a.encode(),b.encode())
        old[12:32]=hashlib.sha1(old[32:]).digest();struct.pack_into('<I',old,8,zlib.adler32(old[12:])&0xffffffff)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'legacy.apk'
            with zipfile.ZipFile(path,'w') as z:z.writestr('classes.dex',old)
            with zipfile.ZipFile(path) as z,patch('apk_installation.identity',return_value={'package':COEXIST_RESOURCES}):changes,report=coexist_entries(z,'update')
        self.assertEqual(report['package'],COEXIST_RESOURCES);self.assertEqual(report['repaired_dex_files'],1)
        self.assertEqual(changes,{'classes.dex':rewrite(raw,ALIASES)[0]})

    def test_legacy_resource_needs_regeneration_and_invalid_dex_cannot_pass_pairing(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SimpleNamespace(root=Path(folder));(store.root/'signing').mkdir();(store.root/'signing/personal-apk-signing-cert.der').write_bytes(b'cert')
            cert=local_certificate(store)
            (store.root/'resource-installations.json').write_text(json.dumps({'coexist':{'package':COEXIST_RESOURCES,'signer':cert}}))
            self.assertTrue(resources_needed(store,[])['coexist'])
            resource={'package':COEXIST_RESOURCES,'kind':'resource','signers':[cert],'dex_identity_valid':False}
            game={'package':COEXIST_GAME,'kind':'game','signers':[cert]}
            self.assertFalse(check([game,resource])['passed'])
            with patch('install_pairs.inspect',return_value=resource),self.assertRaisesRegex(ValueError,'DEX'):validate_install('old.apk',[])
            remember_resource(store,'coexist',COEXIST_RESOURCES,cert)
            self.assertFalse(resources_needed(store,[])['coexist'])
            self.assertTrue(resources_needed(store,[resource])['coexist'])
            resource['dex_identity_valid']=True
            self.assertFalse(resources_needed(store,[resource])['coexist']);self.assertTrue(check([game,resource])['passed'])


if __name__=='__main__':unittest.main()
