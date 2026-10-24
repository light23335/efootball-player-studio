"""Resolve exact native card series for V14 acquisition presentation."""
import struct


def card_series(cpk):
    from native_cpk import Cpk,unwrap
    raw=unwrap(Cpk(cpk).read('common/etc/pesdb/PlayerVariationDetail.bin'))
    if len(raw)%168:raise ValueError('V14 卡种资料长度改变')
    result={}
    for at in range(0,len(raw),168):
        label=raw[at+12:at+140].split(b'\0',1)[0].decode('utf8','replace').replace(' ','').lower()
        series=next((v for p,v in (('bigtime','BigTime'),('showtime','ShowTime'),('epic','Epic'),('legendary','Legendary')) if label.startswith(p)),None)
        if series:result[str(struct.unpack_from('<Q',raw,at)[0])]=series
    return result


