"""Preserve original APK data alignment; replace entries and sign with APK v2.

Uses the Android APK Signature Scheme v2 layout. It never attempts to reuse an
invalid signature or impersonate the original APK signer. Private keys stay in
the local data directory and are never included in player or delta packages.
"""
from pathlib import Path
import copy
import contextlib
import datetime
import hashlib
import os
import shutil
import struct
import tempfile
import zipfile
import zlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

MAGIC=b'APK Sig Block 42'
V2_ID=0x7109871a
RSA_SHA256=0x0103
UINT32_LIMIT=0xffffffff
SIGNING_RESERVE=16*1024


def lp(value):
    return struct.pack('<I',len(value))+value


def read_lp(data,at=0):
    if at+4>len(data):raise ValueError('Truncated length field')
    size=struct.unpack_from('<I',data,at)[0]
    if at+4+size>len(data):raise ValueError('Truncated length-prefixed value')
    return data[at+4:at+4+size],at+4+size


def layout(path):
    with open(path,'rb') as f:
        f.seek(0,2);size=f.tell();f.seek(max(0,size-65557));tail=f.read()
        at=tail.rfind(b'PK\x05\x06')
        if at<0 or at+22>len(tail):raise ValueError('APK end record not found')
        if at+22+struct.unpack_from('<H',tail,at+20)[0]!=len(tail):raise ValueError('Invalid APK end record')
        eocd=size-len(tail)+at
        central=struct.unpack_from('<I',tail,at+16)[0]
        central_size=struct.unpack_from('<I',tail,at+12)[0]
        if central+central_size!=eocd:raise ValueError('APK uses unsupported ZIP64 or trailing directory data')
        signing=central
        if central>=24:
            f.seek(central-24);footer=f.read(24)
            if footer[8:]==MAGIC:
                length=struct.unpack_from('<Q',footer)[0]
                if length<24 or length+8>central:raise ValueError('Invalid APK signing block')
                signing=central-length-8
                f.seek(signing)
                if struct.unpack('<Q',f.read(8))[0]!=length:raise ValueError('Mismatched APK signing block lengths')
        return {'size':size,'data_end':signing,'central':central,'central_size':central_size,'eocd':eocd,'end_record':tail[at:]}


def copy_bytes(src,dst,count):
    while count:
        value=src.read(min(count,4*1024*1024))
        if not value:raise ValueError('Source APK truncated during build')
        dst.write(value);count-=len(value)


def _zip_extra(raw):
    """Retain metadata, dropping obsolete ZIP64/alignment padding fields."""
    out=bytearray();at=0
    while at<len(raw):
        if at+4>len(raw):raise ValueError('APK ZIP extra field is truncated')
        kind,size=struct.unpack_from('<HH',raw,at);end=at+4+size
        if end>len(raw):raise ValueError('APK ZIP extra field exceeds its record')
        if kind not in (1,0xd935):out.extend(raw[at:end])
        at=end
    return bytes(out)


def _local_header(item,offset):
    local=copy.copy(item);local.header_offset=offset
    if item.compress_type==zipfile.ZIP_STORED:
        alignment=16384 if item.filename.endswith('.so') else 4
        name,_=item._encodeFilenameFlags()
        gap=(-(offset+30+len(name)+len(item.extra)))%alignment
        if gap:
            if gap<4:gap+=alignment
            local.extra=item.extra+struct.pack('<HH',0xd935,gap-4)+bytes(gap-4)
    if len(local.extra)>65535:raise ValueError('APK alignment extra field is too large')
    return local.FileHeader(zip64=False)


def _size_error(items,estimate):
    largest=max(items,key=lambda i:i.file_size,default=None)
    label=('；最大文件 '+largest.filename+'（'+str(largest.file_size)+' 字节）') if largest else ''
    return ValueError('APK exceeds the unsigned 32-bit ZIP format：整理有效数据后预计 '
                      +str(estimate)+' 字节，仍超过约 4 GiB 上限'+label+'。请减少内容或拆分配套资源。')


class ContentDigester:
    """APK-v2's three independently chunked regions, fed while writing."""
    def __init__(self):self.pending=bytearray();self.chunks=[]
    def _chunk(self,data):self.chunks.append(hashlib.sha256(b'\xa5'+struct.pack('<I',len(data))+data).digest())
    def update(self,data):
        data=memoryview(data);at=0;block=1024*1024
        if self.pending:
            count=min(block-len(self.pending),len(data));self.pending.extend(data[:count]);at=count
            if len(self.pending)==block:self._chunk(self.pending);self.pending.clear()
        while at+block<=len(data):self._chunk(data[at:at+block]);at+=block
        self.pending.extend(data[at:])
    def end_section(self):
        if self.pending:self._chunk(self.pending);self.pending.clear()
    def digest(self):
        if self.pending:raise ValueError('APK digest section was not finalized')
        return hashlib.sha256(b'\x5a'+struct.pack('<I',len(self.chunks))+b''.join(self.chunks)).digest()


class DigestWriter:
    def __init__(self,stream,digester):self.stream=stream;self.digester=digester
    def write(self,data):
        count=self.stream.write(data)
        if count!=len(data):raise OSError('Incomplete APK write')
        self.digester.update(data);return count
    def tell(self):return self.stream.tell()


def _file_identity(path):
    stat=Path(path).stat()
    return (stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_ino)


def replace_entries(source,output,replacements,*,store_ucas=False,prepare_signing=False):
    """Rewrite current ZIP records, reclaiming superseded local payloads.

    Unchanged compressed bytes are copied directly. Native libraries are
    16-KiB aligned and other stored entries 4-byte aligned. A complete size
    preflight runs before writing the output, with room for APK v2 signing.
    """
    source=Path(source);output=Path(output)
    if output.exists() or source.absolute()==output.absolute():raise ValueError('Output APK must be a new file')
    meta=layout(source)
    with zipfile.ZipFile(source) as z:
        old={i.filename:i for i in z.infolist()}
        if len(old)!=len(z.infolist()):raise ValueError('Source APK has duplicate ZIP entries')
        entries=[copy.copy(i) for i in z.infolist()]
        comment=z.comment
    if any(name.startswith('/') or '\\' in name or '..' in name.split('/') for name in replacements):
        raise ValueError('Invalid replacement path')
    entries.extend(zipfile.ZipInfo(name,(2026,1,1,0,0,0)) for name in replacements if name not in old)
    if len(entries)>=65535:raise ValueError('Too many APK entries for non-ZIP64 format')
    with contextlib.ExitStack() as stack,source.open('rb') as src:
        plans=[];cursor=0;stored=[]
        for item in entries:
            name=item.filename
            if name.startswith('/') or '\\' in name or '..' in name.split('/'):
                raise ValueError('Invalid replacement path')
            if item.flag_bits&1:raise ValueError('Encrypted ZIP entries are not supported in APK')
            item.extra=_zip_extra(item.extra)
            item.flag_bits&=~8
            stream=None;data=None;offset=None
            if name in replacements:
                data=replacements[name];item.file_size=len(data);item.CRC=zlib.crc32(data)&0xffffffff
                if item.file_size>=UINT32_LIMIT:raise _size_error(entries,item.file_size)
                if store_ucas and name.lower().endswith('.ucas'):
                    if item.compress_type!=zipfile.ZIP_STORED:stored.append({'name':name,'bytes':len(data)})
                    item.compress_type=zipfile.ZIP_STORED
                if item.compress_type==zipfile.ZIP_DEFLATED:
                    stream=stack.enter_context(tempfile.SpooledTemporaryFile(max_size=8*1024*1024,dir=output.parent))
                    encoder=zlib.compressobj(9,zlib.DEFLATED,-15)
                    view=memoryview(data)
                    for at in range(0,len(view),4*1024*1024):stream.write(encoder.compress(view[at:at+4*1024*1024]))
                    stream.write(encoder.flush());item.compress_size=stream.tell();stream.seek(0);data=None
                elif item.compress_type==zipfile.ZIP_STORED:item.compress_size=len(data)
                else:raise ValueError('Unsupported APK entry compression')
            else:
                previous=old[name];src.seek(previous.header_offset);header=src.read(30)
                if len(header)!=30 or header[:4]!=b'PK\x03\x04':raise ValueError('APK local ZIP header is invalid')
                flags,method=struct.unpack_from('<HH',header,6);n,e=struct.unpack_from('<HH',header,26)
                local_name=src.read(n).decode('utf8' if flags&0x800 else 'cp437')
                if local_name!=name or method!=item.compress_type:raise ValueError('APK local/central ZIP entries disagree')
                offset=previous.header_offset+30+n+e
                if offset+item.compress_size>meta['data_end']:raise ValueError('APK compressed entry exceeds source data')
            if max(item.file_size,item.compress_size,cursor)>=UINT32_LIMIT:raise _size_error(entries,cursor)
            item.header_offset=cursor;header=_local_header(item,cursor);cursor+=len(header)+item.compress_size
            plans.append((item,header,offset,stream,data))
        central=cursor
        central_size=sum(46+len(i._encodeFilenameFlags()[0])+len(i.extra)+len(i.comment) for i in entries)
        estimate=central+central_size+22+len(comment)+SIGNING_RESERVE
        if estimate>=UINT32_LIMIT:raise _size_error(entries,estimate)
        digester=ContentDigester()if prepare_signing else None
        with output.open('xb') as raw_dst:
            dst=DigestWriter(raw_dst,digester)if digester else raw_dst
            for item,header,offset,stream,data in plans:
                dst.write(header)
                if stream is not None:copy_bytes(stream,dst,item.compress_size)
                elif data is not None:dst.write(data)
                else:src.seek(offset);copy_bytes(src,dst,item.compress_size)
            if dst.tell()!=central:raise ValueError('APK rewritten local records do not match preflight')
            if digester:digester.end_section()
            for item in entries:
                _write_central(dst,item)
            if digester:digester.end_section()
            dst.write(struct.pack('<I4H2IH',0x06054b50,0,0,len(entries),len(entries),central_size,central,len(comment)))
            dst.write(comment)
            if digester:digester.end_section()
    result=layout(output)
    if digester:result.update(content_digest=digester.digest().hex(),unsigned_identity=_file_identity(output))
    result['compaction']={'compact_rewrite':True,'source_bytes':meta['size'],'unsigned_bytes':result['size'],'entries':len(entries),
                          'stored_ucas':stored,'v2_digest_streamed':bool(digester)}
    return result


def _write_central(dst,item):
    name,flags=item._encodeFilenameFlags()
    y,mo,day,h,mi,s=item.date_time
    dos_time=h<<11|mi<<5|s//2;dos_date=(y-1980)<<9|mo<<5|day
    fields=(0x02014b50,item.create_version|(item.create_system<<8),item.extract_version,flags,item.compress_type,
            dos_time,dos_date,item.CRC,item.compress_size,item.file_size,len(name),len(item.extra),len(item.comment),
            0,item.internal_attr,item.external_attr,item.header_offset)
    dst.write(struct.pack('<I6H3I5H2I',*fields));dst.write(name);dst.write(item.extra);dst.write(item.comment)


def content_digest(path,meta=None):
    meta=meta or layout(path)
    end=bytearray(meta['end_record']);struct.pack_into('<I',end,16,meta['data_end'])
    chunks=[]
    with open(path,'rb') as f:
        for start,length in [(0,meta['data_end']),(meta['central'],meta['central_size'])]:
            f.seek(start)
            while length:
                b=f.read(min(1024*1024,length))
                if not b:raise ValueError('APK truncated while hashing')
                length-=len(b);chunks.append(hashlib.sha256(b'\xa5'+struct.pack('<I',len(b))+b).digest())
    for start in range(0,len(end),1024*1024):
        b=end[start:start+1024*1024];chunks.append(hashlib.sha256(b'\xa5'+struct.pack('<I',len(b))+b).digest())
    return hashlib.sha256(b'\x5a'+struct.pack('<I',len(chunks))+b''.join(chunks)).digest()


def local_signer(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    private=directory/'personal-apk-signing-key.pem';certificate=directory/'personal-apk-signing-cert.der'
    if private.exists()!=certificate.exists():raise ValueError('Signing identity is incomplete; restore its backup before building updates')
    if private.exists():
        key=serialization.load_pem_private_key(private.read_bytes(),password=None)
        cert=x509.load_der_x509_certificate(certificate.read_bytes())
        if key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)!=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo):
            raise ValueError('Signing certificate does not match private key')
    else:
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Personal Offline Player Studio')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1))
              .not_valid_after(now+datetime.timedelta(days=10950)).sign(key,hashes.SHA256()))
        # The enclosing data directory is excluded from portable/source/delta archives.
        with private.open('xb') as f:f.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        with certificate.open('xb') as f:f.write(cert.public_bytes(serialization.Encoding.DER))
    return key,cert


def sign_v2(unsigned,output,key,certificate,*,prepared=None,consume=False):
    unsigned=Path(unsigned);output=Path(output)
    if output.exists() or unsigned.absolute()==output.absolute():raise ValueError('Signed output must be a new file')
    meta=layout(unsigned)
    if meta['data_end']!=meta['central']:raise ValueError('Expected unsigned intermediate APK')
    reusable=(prepared is not None and prepared.get('unsigned_identity')==_file_identity(unsigned)
              and all(prepared.get(k)==meta[k]for k in('size','data_end','central','central_size','end_record')))
    digest=bytes.fromhex(prepared['content_digest'])if reusable else content_digest(unsigned,meta)
    if len(digest)!=32:raise ValueError('Prepared APK digest is invalid')
    cert=certificate.public_bytes(serialization.Encoding.DER)
    public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    signed_data=lp(lp(struct.pack('<I',RSA_SHA256)+lp(digest)))+lp(lp(cert))+lp(b'')
    signature=key.sign(signed_data,padding.PKCS1v15(),hashes.SHA256())
    signer=lp(signed_data)+lp(lp(struct.pack('<I',RSA_SHA256)+lp(signature)))+lp(public)
    value=lp(lp(signer))
    pair=struct.pack('<QI',len(value)+4,V2_ID)+value
    # Pad the signing block as Android's own apksigner does.
    gap=(-len(pair)-32)%4096
    if gap<12:gap+=4096
    pair+=struct.pack('<QI',gap-8,0x42726577)+b'\0'*(gap-12)
    length=len(pair)+24;block=struct.pack('<Q',length)+pair+struct.pack('<Q',length)+MAGIC
    if meta['central']+len(block)>=UINT32_LIMIT or meta['size']+len(block)>=UINT32_LIMIT:
        raise _size_error([],meta['size']+len(block))
    end=bytearray(meta['end_record']);struct.pack_into('<I',end,16,meta['central']+len(block))
    if consume:
        # Only the caller-owned unsigned intermediate is consumed. Move the
        # directory backwards in bounded buffers; never recopy the payload.
        with unsigned.open('r+b')as stream:
            remaining=meta['central_size']
            while remaining:
                count=min(4*1024*1024,remaining);start=meta['central']+remaining-count
                stream.seek(start);data=stream.read(count)
                if len(data)!=count:raise ValueError('APK central directory was truncated')
                stream.seek(start+len(block));stream.write(data);remaining-=count
            stream.seek(meta['central']);stream.write(block)
            stream.seek(meta['central']+len(block)+meta['central_size']);stream.write(end)
            stream.truncate();stream.flush()
        # Reserve the destination exclusively, then publish our completed file.
        with output.open('xb'):pass
        try:os.replace(unsigned,output)
        except Exception:output.unlink(missing_ok=True);raise
    else:
        with unsigned.open('rb') as src,output.open('xb') as dst:
            copy_bytes(src,dst,meta['central']);dst.write(block)
            copy_bytes(src,dst,meta['central_size']);dst.write(end)
    return {'signer_sha256':hashlib.sha256(cert).hexdigest(),'content_digest':digest.hex(),'size':output.stat().st_size,
            'digest_reused':reusable,'payload_recopy_avoided':bool(consume)}


def verify_v2(path):
    """Independent parse, public-key verification and APK content digest check."""
    meta=layout(path)
    if meta['data_end']==meta['central']:raise ValueError('No APK v2 signing block')
    with open(path,'rb') as f:
        f.seek(meta['data_end']);block=f.read(meta['central']-meta['data_end'])
    at=8;found=None
    while at<len(block)-24:
        length,kind=struct.unpack_from('<QI',block,at)
        if length<4 or at+8+length>len(block)-24:raise ValueError('Invalid signing block entry')
        if kind==V2_ID:found=block[at+12:at+8+length]
        at+=8+length
    if found is None:raise ValueError('No APK Signature Scheme v2 entry')
    signers,_=read_lp(found);signer,end=read_lp(signers)
    if end!=len(signers):raise ValueError('Only single-signer APKs are supported by this verifier')
    signed,at=read_lp(signer);signatures,at=read_lp(signer,at);public,at=read_lp(signer,at)
    if at!=len(signer):raise ValueError('Trailing signer data')
    digests,at=read_lp(signed);certificates,at=read_lp(signed,at);attributes,at=read_lp(signed,at)
    record,_=read_lp(digests);algorithm=struct.unpack_from('<I',record)[0];expected,_=read_lp(record,4)
    signature_record,_=read_lp(signatures);signature_algorithm=struct.unpack_from('<I',signature_record)[0];signature,_=read_lp(signature_record,4)
    if algorithm!=RSA_SHA256 or signature_algorithm!=RSA_SHA256:raise ValueError('Only RSA/SHA256 v2 verification is supported')
    der,_=read_lp(certificates);certificate=x509.load_der_x509_certificate(der)
    if certificate.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)!=public:
        raise ValueError('APK public key does not match signing certificate')
    certificate.public_key().verify(signature,signed,padding.PKCS1v15(),hashes.SHA256())
    actual=content_digest(path,meta)
    if actual!=expected:raise ValueError('APK content digest mismatch')
    return {'verified_v2':True,'signer_sha256':hashlib.sha256(der).hexdigest(),'content_digest':actual.hex()}
