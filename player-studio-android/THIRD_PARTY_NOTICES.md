# Third-party components

The Android host reuses the public Player Studio 1.8.4 editing and APK-writing
core. No game APK, extracted game cache, private player, face model or signing
key is distributed with this software.

- Chaquopy 17.1.0: MIT, https://github.com/chaquo/chaquopy
- CityHash: MIT, https://github.com/google/cityhash (COPYING beside the source)
- AssetStudio texture decoders: MIT, https://github.com/Perfare/AssetStudio
  (LICENSE beside the source)
- FP16: MIT, https://github.com/Maratyszcza/FP16
- JCodec 0.2.5: FreeBSD/BSD, https://github.com/jcodec/jcodec
- CUE4Parse serialization format references: Apache-2.0,
  https://github.com/FabianFG/CUE4Parse (license and notice in licenses/).
- Python, NumPy, Pillow, cryptography and their native runtime dependencies:
  their licenses are included by the Chaquopy wheel packaging in the APK.
- Three.js: MIT, license included in the public core web/vendor/three directory.

Copies of the Android-specific license texts are in licenses/ and the packaged
studio-bundle.zip/licenses/. The codec bridge and portable readers are source
files in this project. They do not invoke a Windows executable or remote PC.

Custom movie muxing: WannaCRI 0.3.3 (MIT), ffmpeg-python 0.2.0 (Apache-2.0), python-json-logger 2.0.7 (BSD-2-Clause), tqdm 4.70.1 (MIT/MPL-2.0), future 1.0.0 (MIT), colorama 0.4.6 (BSD-3-Clause). License texts are packaged in resources/third-party-licenses/. Android video encoding uses platform MediaCodec.
