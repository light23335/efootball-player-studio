"""Replace a launcher's drawable file without changing resource IDs or Java code."""
import hashlib,struct,zlib
from pathlib import PurePosixPath


def chunks(raw,start,end):
    at=start
    while at<end:
        if at+8>end:raise ValueError('Truncated Android resource header')
        kind,header,size=struct.unpack_from('<HHI',raw,at)
        if header<8 or size<header or at+size>end:raise ValueError('Invalid Android resource chunk')
        yield at,kind,header,size
        at+=size
    if at!=end:raise ValueError('Invalid Android resource boundary')


def png_size(raw):
    if raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Launcher image must be PNG')
    at=8;size=None;ended=False
    while at<len(raw):
        if at+12>len(raw):raise ValueError('Truncated launcher PNG')
        length=struct.unpack_from('>I',raw,at)[0];kind=raw[at+4:at+8];end=at+12+length
        if end>len(raw) or zlib.crc32(raw[at+4:end-4])&0xffffffff!=struct.unpack_from('>I',raw,end-4)[0]:raise ValueError('Launcher PNG CRC failure')
        if at==8:
            if kind!=b'IHDR' or length!=13:raise ValueError('Launcher PNG has no IHDR')
            size=struct.unpack_from('>II',raw,at+8)
            if size[0]!=size[1] or not 48<=size[0]<=1024:raise ValueError('Launcher PNG must be a square of 48–1024 pixels')
        if kind==b'IEND':ended=True
        at=end
    if not ended:raise ValueError('Launcher PNG has no IEND')
    return size


def drawable_paths(table,ids):
    """Resolve simple TYPE_STRING resource values in all configurations."""
    from android_manifest import Manifest
    if len(table)<12 or struct.unpack_from('<HHI',table)!=(2,12,len(table)):raise ValueError('Invalid resources.arsc')
    found={};pool=None
    top=list(chunks(table,12,len(table)))
    for at,kind,header,size in top:
        if kind==1:
            if pool is not None:raise ValueError('Multiple global Android string pools')
            pool=(at,header,size,Manifest(struct.pack('<HHI',3,8,size+8)+table[at:at+size]))
    if pool is None:raise ValueError('Missing Android global string pool')
    strings=pool[3].strings
    for at,kind,header,size in top:
        if kind!=0x200:continue
        package=struct.unpack_from('<I',table,at+8)[0]
        type_offset=struct.unpack_from('<I',table,at+284)[0] if header>=288 else 0
        for pos,typ,head,total in chunks(table,at+header,at+size):
            if typ!=0x201:continue
            type_id,flags=struct.unpack_from('<BB',table,pos+8)
            count,start=struct.unpack_from('<II',table,pos+12)
            for rid in ids:
                entry=rid&0xffff
                if rid>>24!=package or (rid>>16)&255!=type_id+type_offset:continue
                if flags:raise ValueError('Unsupported sparse launcher resource table')
                if entry>=count:continue
                offset=struct.unpack_from('<I',table,pos+head+4*entry)[0]
                if offset==0xffffffff:continue
                location=pos+start+offset
                if location+16>pos+total:raise ValueError('Invalid launcher resource offset')
                entry_size,entry_flags=struct.unpack_from('<HH',table,location)
                if entry_flags&1:raise ValueError('Launcher drawable is a complex resource')
                value=location+entry_size
                if table[value+3]!=3:raise ValueError('Launcher drawable is not a file resource')
                index=struct.unpack_from('<I',table,value+4)[0]
                if index>=len(strings):raise ValueError('Invalid launcher resource string')
                found.setdefault(rid,set()).add((index,strings[index]))
    if set(found)!=set(ids):raise ValueError('Launcher resource ID was not found')
    return pool,found


def prepare_launcher(archive,png):
    from android_manifest import Manifest
    dimensions=png_size(png)
    manifest=Manifest(archive.read('AndroidManifest.xml'))
    ids={a['value'] for _,name,attrs in manifest.nodes() if name=='application' for a in attrs if a['name']in ('icon','roundIcon') and a['type']==1}
    if not ids:raise ValueError('Android manifest has no launcher drawable reference')
    table=archive.read('resources.arsc');pool,found=drawable_paths(table,ids)
    at,header,size,decoded=pool;part=bytearray(table[at:at+size]);flags,start=struct.unpack_from('<II',part,16)
    changes={};removed=set();paths=[]
    for entries in found.values():
        for index,old in sorted(entries):
            path=PurePosixPath(old)
            if not old.startswith('res/') or '..'in path.parts or path.suffix not in ('.xml','.png'):raise ValueError('Unsupported launcher resource file: '+old)
            if old not in archive.namelist():raise ValueError('Launcher file is missing: '+old)
            new=str(path.with_suffix('.png'));offset=start+struct.unpack_from('<I',part,header+index*4)[0]
            def length(pos):
                if flags&256:
                    value=part[pos];return ((((value&127)<<8)|part[pos+1],pos+2) if value&128 else (value,pos+1))
                value=struct.unpack_from('<H',part,pos)[0];return ((((value&32767)<<16)|struct.unpack_from('<H',part,pos+2)[0],pos+4) if value&32768 else (value,pos+2))
            count,offset=length(offset)
            if flags&256:count,offset=length(offset);codec='utf8'
            else:count*=2;codec='utf-16le'
            before=old.encode(codec);after=new.encode(codec)
            if len(before)!=len(after) or count!=len(before):raise ValueError('Launcher path must preserve string length')
            if bytes(part[offset:offset+count])not in (before,after):raise ValueError('Launcher string pool mismatch')
            part[offset:offset+count]=after
            if old!=new:removed.add(old)
            changes[new]=png;paths.append(new)
    # Renaming XML to PNG keeps every string index and table offset stable.
    # Clear the sorted flag if it was set; all non-pool chunks stay byte-identical.
    struct.pack_into('<I',part,16,flags&~1)
    changes['resources.arsc']=table[:at]+part+table[at+size:]
    _,check=drawable_paths(changes['resources.arsc'],ids)
    assert {p for entries in check.values() for _,p in entries}==set(paths)
    return changes,removed,{'sha256':hashlib.sha256(png).hexdigest(),'width':dimensions[0],'height':dimensions[1],
                            'resource_ids':[hex(i)for i in sorted(ids)],'files':sorted(set(paths)),'matches_pc_icon':True}
