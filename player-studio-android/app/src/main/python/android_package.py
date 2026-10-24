"""Low-storage Android signing and the exact original binding reference."""
from pathlib import Path
import hashlib,os,shutil,struct
import apk_format as apk
from native_package import NativePackage as BasePackage

def sign_v2_in_place(unsigned,output,key,certificate):
    """Sign the task-owned unsigned file without a second multi-GB copy."""
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    unsigned,output=Path(unsigned),Path(output)
    if output.exists() or unsigned.absolute()==output.absolute():raise ValueError('签名输出必须是新的文件')
    meta=apk.layout(unsigned)
    if meta['data_end']!=meta['central']:raise ValueError('签名前的 APK 必须是无签名临时文件')
    digest=apk.content_digest(unsigned,meta);lp=apk.lp
    cert=certificate.public_bytes(serialization.Encoding.DER)
    public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    signed=lp(lp(struct.pack('<I',apk.RSA_SHA256)+lp(digest)))+lp(lp(cert))+lp(b'')
    signature=key.sign(signed,padding.PKCS1v15(),hashes.SHA256())
    signer=lp(signed)+lp(lp(struct.pack('<I',apk.RSA_SHA256)+lp(signature)))+lp(public)
    value=lp(lp(signer));pair=struct.pack('<QI',len(value)+4,apk.V2_ID)+value
    gap=(-len(pair)-32)%4096
    if gap<12:gap+=4096
    pair+=struct.pack('<QI',gap-8,0x42726577)+b'\0'*(gap-12)
    length=len(pair)+24;block=struct.pack('<Q',length)+pair+struct.pack('<Q',length)+apk.MAGIC
    end=bytearray(meta['end_record']);struct.pack_into('<I',end,16,meta['central']+len(block))
    with unsigned.open('r+b') as f:
        f.seek(meta['central']);directory=f.read(meta['central_size'])
        f.seek(meta['central']);f.write(block);f.write(directory);f.write(end);f.truncate();f.flush();os.fsync(f.fileno())
    unsigned.replace(output)
    return {'signer_sha256':hashlib.sha256(cert).hexdigest(),'content_digest':digest.hex(),'size':output.stat().st_size}

def reference_source(assets):
    container=next((p for p in assets.containers if p.path.stem=='pc3600_mobile_and'),None)
    if container is None:raise ValueError('离线资源包缺少原版脸模骨架模板')
    path='../../../PesMobile/Content/Assets/character/RealFace/SK_133543_Face.uasset'
    class Original:
        def raw(self,name):
            return container.read(path) if assets.normalize(name)==path else assets.raw(name)
    return Original()

class AndroidPackage(BasePackage):
    def reference_model(self):
        target=self.library.converted/'PesMobile/Content/Assets/character/RealFace/SK_133543_Face-bind-template.glb'
        textured=target.with_name(target.stem+'-native.glb')
        if not textured.is_file():
            from portable_decode import mesh_glb
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(mesh_glb(reference_source(self.library.decoder),'/Game/Assets/character/RealFace/SK_133543_Face'))
            self.library.texture_model(target,{'path':'PesMobile/Content/Assets/character/RealFace/SK_133543_Face.uasset'})
        return textured
    def start(self,body):
        source=body.get('companion') if body.get('operation')=='companion' else body.get('apk')
        if source and Path(source).is_file():
            need=Path(source).stat().st_size+512*1024*1024
            free=shutil.disk_usage(self.store.root).free
            if free<need:raise ValueError(f'手机可用空间不足：本次至少需要 {need/1024**3:.1f} GB，可用 {free/1024**3:.1f} GB')
        return super().start(body)
