#include <cstdint>
#include <cstddef>
#include "vendor/cityhash/city.h"
#include "vendor/texture/astc.h"
#include "vendor/texture/etc.h"
#include "vendor/texture/bcn.h"
extern "C" uint64_t studio_cityhash(const char *data, size_t size) { return CityHash64(data, size); }
extern "C" int studio_astc(const uint8_t *data, size_t size, int width, int height, int bx, int by, uint32_t *out) {
    if (width < 1 || height < 1 || width > 8192 || height > 8192 || bx < 4 || bx > 12 || by < 4 || by > 12) return 0;
    size_t expected = ((width + bx - 1) / bx) * ((height + by - 1) / by) * 16;
    if (size != expected) return 0;
    return decode_astc(data, width, height, bx, by, out);
}
extern "C" int studio_blocks(const uint8_t *data, size_t size, int width, int height, int format, uint32_t *out) {
    if(width<1 || height<1 || width>8192 || height>8192) return 0;
    size_t expected=((width+3)/4)*((height+3)/4)*((format==1 || format==3 || format==4)?8:16);
    if(size!=expected) return 0;
    switch(format) {
        case 1: return decode_etc2(data,width,height,out);
        case 2: return decode_etc2a8(data,width,height,out);
        case 3: return decode_etc2a1(data,width,height,out);
        case 4: return decode_bc1(data,width,height,out);
        case 5: return decode_bc3(data,width,height,out);
        case 6: return decode_bc5(data,width,height,out);
        case 7: return decode_bc7(data,width,height,out);
    }
    return 0;
}
