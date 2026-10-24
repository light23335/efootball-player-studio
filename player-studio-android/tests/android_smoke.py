"""Executed only by debug instrumentation in an isolated Android device."""
from pathlib import Path
import hashlib,json,os,struct,tempfile,urllib.request,urllib.parse,zipfile

def run(home,native_dir,fixtures):
    from android_backend import start,stop
    runtime=json.loads(start(home,native_dir));fixtures=Path(fixtures)
    import numpy as np
    from PIL import Image
    from cityhash import CityHash64
    from portable_decode import texture_image,mesh_glb,material_json
    from native_appearance import original_face_skin
    from native_glb import Glb
    from native_binding_source import verify_installer
    from personal_binding import fingerprint
    from android_package import sign_v2_in_place
    import apk_format,marshal
    manifest=json.loads((fixtures/'manifest.json').read_text())
    class FixtureAssets:
        def raw(self,path):
            if path.startswith('/Game/'):path='PesMobile/Content/'+path[6:]+('' if path.endswith(('.uasset','.ubulk')) else '.uasset')
            path=path.removeprefix('../../../');item=manifest['files'][path];raw=(fixtures/item['file']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==item['sha256'];return raw
    assets=FixtureAssets();passed=[]
    def check(name,fn):
        value=fn();passed.append({'check':name,'result':value});print('StudioProbe PASS '+name,flush=True);return value
    def hashes():
        for text,value in manifest['cityhash_vectors']:assert CityHash64(text.encode())==value
        return len(manifest['cityhash_vectors'])
    check('native_cityhash',hashes)
    def documents():
        from android_files import register,unregister
        source=fixtures/'preview.m2v';alias=fixtures/'authorized-document.apk';alias.touch()
        fd=os.open(source,os.O_RDONLY);register(alias,fd)
        try:
            assert alias.stat().st_size==source.stat().st_size
            alternate=Path(str(alias).replace('/data/user/0/','/data/data/'))
            assert alternate.read_bytes()==source.read_bytes()
            with alias.open('rb') as a,alias.open('rb') as b:
                a.seek(25);assert b.read(4)==source.read_bytes()[:4];assert a.tell()==25
                assert a.read(20)==source.read_bytes()[25:45]
            try:alias.open('wb')
            except PermissionError:pass
            else:raise AssertionError('Read-only source could be overwritten')
        finally:unregister(alias);os.close(fd);alias.unlink()
        return 'independent cursors and read-only access'
    check('android_document_readers',documents)
    def textures():
        for path,expect in manifest['textures'].items():
            image=texture_image(assets,path);assert list(image.size)==expect['size']
            assert hashlib.sha256(image.tobytes()).hexdigest()==expect['rgba_sha256']
        return len(manifest['textures'])
    check('native_texture_decoders',textures)
    def skeleton():
        glb=Glb(mesh_glb(assets,'/Game/Assets/character/RealFace/SK_133543_Face'))
        names=[glb.doc['nodes'][j]['name'] for j in glb.doc['skins'][0]['joints']]
        matrices=glb.read(glb.doc['skins'][0]['inverseBindMatrices'])
        assert names==manifest['bone_names']
        error=float(np.abs(matrices-np.asarray(manifest['inverse_bind_matrices'])).max());assert error<1e-6
        return {'bones':len(names),'maximum_bind_error':error}
    check('original_binding_skeleton',skeleton)
    def materials():
        props=material_json(assets,'/Game/Assets/character/RealFace/MI_105029_Head_FaceUpcon_HQ')[0]['Properties']
        diffuse=next(p['ParameterValue']['ObjectPath'] for p in props['TextureParameterValues'] if p['ParameterInfo']['Name']=='BaseColorMap')
        assert diffuse.endswith('/T_105029_Face_D');return diffuse.rsplit('/',1)[-1]
    check('original_material_texture_link',materials)
    def skin():
        raw=assets.raw('/Game/Assets/character/RealFace/SK_105029_Face')
        updated,report=original_face_skin(raw,{'skin_tone':4,'appearance_source_id':'105029'},fixtures)
        assert updated==raw and report['mode']=='preserved-original';return 'unchanged'
    check('firmino_184_fix',skin)
    def signing():
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);source=folder/'source.apk';unsigned=folder/'unsigned.apk';output=folder/'signed.apk'
            with zipfile.ZipFile(source,'w') as z:z.writestr('assets/example',b'original data');z.writestr('lib/arm64-v8a/example.so',b'fixture'*10000)
            apk_format.replace_entries(source,unsigned,{'assets/example':b'new data'})
            key,cert=apk_format.local_signer(folder/'signing');sign_v2_in_place(unsigned,output,key,cert)
            result=apk_format.verify_v2(output);assert not unsigned.exists()
            with zipfile.ZipFile(output) as z:assert z.read('assets/example')==b'new data'
            return result
    check('apk_v2_sign_and_independent_verify',signing)
    def binding():
        resources=Path(home)/'bundle/resources';original=json.loads((resources/'native-binding-profile.json').read_text())
        profile=json.loads((resources/'native-route-templates.json').read_text());profile['external_routes']=True
        payload={'original_fingerprint':fingerprint(original),'routes':[{'cardId':99002001,'suiteDonorId':99002001,'portraitKey':'8900001','modelFaceKey':'8900001'}],'profile':profile}
        result=verify_installer(marshal.loads((fixtures/'installer.marshal').read_bytes()),payload)
        assert result['page_bytes']==4096;return result
    check('v15_runtime_binding_preflight',binding)
    def movie():
        from java import jclass
        dest=fixtures/'preview.webm';result=json.loads(str(jclass('com.playerstudio.editor.MovieBridge').transcode(str(fixtures/'preview.m2v'),str(dest))))
        assert dest.read_bytes().startswith(b'\x1aE\xdf\xa3') and result['frames']>0;return result
    check('phone_mpeg2_to_webm',movie)
    def http():
        parsed=urllib.parse.urlsplit(runtime['url']);token=urllib.parse.parse_qs(parsed.query)['token'][0]
        req=urllib.request.Request('http://127.0.0.1:'+str(runtime['port'])+'/api/bootstrap',headers={'X-Studio-Token':token})
        with urllib.request.urlopen(req) as response:bootstrap=json.load(response)
        assert bootstrap['version']=='1.8.4' and bootstrap['library']['platform']=='android'
        import android_backend
        assert android_backend._server.library.tool.is_file(),'Portable converter marker missing'
        return {'version':bootstrap['version'],'platform':bootstrap['library']['platform']}
    check('local_editor_http_and_catalogue',http)
    def export_blob():
        parsed=urllib.parse.urlsplit(runtime['url']);token=urllib.parse.parse_qs(parsed.query)['token'][0]
        base='http://127.0.0.1:'+str(runtime['port'])
        headers={'X-Studio-Token':token,'X-Studio-Filename':urllib.parse.quote('安卓导出.png'),'Content-Type':'image/png'}
        payload=b'\x89PNG\r\n\x1a\nphone-local-export'
        with urllib.request.urlopen(urllib.request.Request(base+'/api/android-export',data=payload,headers=headers)) as response:result=json.load(response)
        with urllib.request.urlopen(urllib.request.Request(base+result['url'],headers={'X-Studio-Token':token})) as response:assert response.read()==payload
        assert result['filename']=='安卓导出.png'
        (Path(home)/'data/exports'/urllib.parse.unquote(result['url'].rsplit('/',1)[-1])).unlink()
        return 'blob export bytes and Unicode filename round trip'
    check('android_blob_export_round_trip',export_blob)
    stop();return json.dumps({'passed':len(passed),'checks':passed,'abi':os.uname().machine})
