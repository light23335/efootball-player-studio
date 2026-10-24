"""Android CityHash64 shim backed by the original MIT-licensed C++ code."""
import ctypes,os
_lib=None
def library():
    global _lib
    if _lib is None:
        _lib=ctypes.CDLL(os.environ['STUDIO_CODECS'])
        _lib.studio_cityhash.argtypes=[ctypes.c_char_p,ctypes.c_size_t]
        _lib.studio_cityhash.restype=ctypes.c_uint64
    return _lib
def CityHash64(value):
    if isinstance(value,str):value=value.encode()
    return int(library().studio_cityhash(value,len(value)))
