"""Low-storage Android signing and the exact original binding reference."""
from pathlib import Path
import shutil
import apk_format as apk
from native_package import NativePackage as BasePackage

def sign_v2_in_place(unsigned,output,key,certificate,*,prepared=None,consume=True):
    """Use the shared signer; legacy Android callers still consume their temp file.

    Resource and game exports both supply the prepared digest and consume=True.
    Sharing the implementation keeps its bounds checks, bounded-memory directory
    move, digest invalidation and exclusive output handling identical to PC.
    """
    return apk.sign_v2(unsigned,output,key,certificate,prepared=prepared,consume=consume)

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
