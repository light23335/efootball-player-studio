"""V13 ARM64 manager proficiency calculation, with single-precision steps."""
import struct


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def factor(proficiency):
    if proficiency is None or proficiency == 127:
        return 1.0
    value=f32(proficiency)
    if proficiency < 90:
        x=f32(value-f32(99))
        value=f32(f32(f32(f32(x*f32(x*f32(-38)))/f32(99))/f32(99))+f32(104))
    else:
        slope=struct.unpack('<f',struct.pack('<I',0x3d46a7f0))[0]
        offset=struct.unpack('<f',struct.pack('<I',0x42c68189))[0]
        value=f32(f32(value*slope)+offset)
    return f32(value/f32(100))


def displayed(trained, player_boost, coach_boost, multiplier):
    delta=int(f32(f32(multiplier*f32(trained))-f32(trained)))
    return max(40,min(120,trained+delta+player_boost+coach_boost))
