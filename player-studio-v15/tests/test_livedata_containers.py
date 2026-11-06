import copy,hashlib,io,json,unittest,zipfile
from native_live import container_metadata,content_fingerprint,compile_template,verify_template,verify_apk,_reserve

class LiveContainerTests(unittest.TestCase):
    def fixture(self,stale=False):
        data={f'pc9262_mobile_and{ext}':('actual'+ext).encode() for ext in('.pak','.ucas','.utoc')}
        metadata={name:{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}for name,raw in data.items()}
        template={'version_file':json.dumps({'version':10,'dt870Hash':'old','dt870FileSize':1,'dt880':[{'name':'pc9262','hash':'old','hashFileSize':1,'ucas':'old','ucasFileSize':1,'utoc':'old','utocFileSize':1}]}),
                  'livedata_list':[{'name':'dt870_mobile_and.cpk','size':1,'url':'keep-cpk'}]+[{'name':name,'size':1,'url':'keep-'+name}for name in data]}
        cpk=b'cpk';compiled=compile_template(template,cpk,11,metadata)
        if stale:
            info=json.loads(compiled['version_file']);info['dt880'][0]['ucas']='old';compiled['version_file']=json.dumps(info)
        meta={'bytes':len(cpk),'sha256':hashlib.sha256(cpk).hexdigest()}
        doc={'live_data':verify_template(compiled,cpk),'resource_files':{'dt870_mobile_and.cpk':meta}}
        entries={'custom-resources/legends-v10/dt870_mobile_and.cpk':cpk,'livedata/dt870_mobile_and.cpk':cpk,
                 'work/templates/CMD_LOGIN_LIVEDATA.json':json.dumps(compiled).encode(),
                 'custom-resources/personal-player-studio/players.json':json.dumps(doc).encode(),
                 **{'livedata/'+name:raw for name,raw in data.items()}}
        manifest={'files':[{'path':n,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}for n,raw in entries.items()]}
        entries['release-manifest.json']=json.dumps(manifest).encode()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w')as z:
            for name,raw in entries.items():z.writestr('assets/gateway-release/'+name,raw)
        stream.seek(0)
        return stream,template,data,metadata,compiled

    def test_changed_native_container_updates_every_advertised_hash_size_and_download_row(self):
        stream,template,data,metadata,compiled=self.fixture();old=copy.deepcopy(template)
        info=json.loads(compiled['version_file'])['dt880'][0]
        for field,ext,size in(('hash','.pak','hashFileSize'),('ucas','.ucas','ucasFileSize'),('utoc','.utoc','utocFileSize')):
            row=metadata['pc9262_mobile_and'+ext];self.assertEqual(info[field],row['sha256']);self.assertEqual(info[size],row['bytes'])
        self.assertEqual(template,old);self.assertEqual(verify_apk(stream)['native_container_entries_checked'],3)

    def test_final_gate_rejects_exact_stale_native_hash_even_when_cpk_is_valid(self):
        stream,*_=self.fixture(stale=True)
        with self.assertRaisesRegex(ValueError,'原生容器版本清单'):verify_apk(stream)

    def test_streamed_container_metadata_prefers_final_replacements(self):
        stream,template,data,metadata,_=self.fixture()
        replacement=b'new stadium texture and mesh data'
        with zipfile.ZipFile(stream)as z:
            result=container_metadata(z,{'assets/gateway-release/livedata/pc9262_mobile_and.ucas':replacement},template)
        self.assertEqual(result['pc9262_mobile_and.ucas'],{'bytes':len(replacement),'sha256':hashlib.sha256(replacement).hexdigest()})
        self.assertEqual(result['pc9262_mobile_and.utoc'],metadata['pc9262_mobile_and.utoc'])

    def test_stadium_only_change_advances_live_version_even_with_identical_player_cpk(self):
        _,template,_,metadata,_=self.fixture();changed=copy.deepcopy(metadata)
        changed['pc9262_mobile_and.ucas']['sha256']='c'*64
        a=content_fingerprint('same-cpk',metadata);b=content_fingerprint('same-cpk',changed)
        self.assertNotEqual(a,b)
        version,registry=_reserve({},'V17',template,a);other,_=_reserve(registry,'V17',template,b)
        self.assertGreater(other,version)
