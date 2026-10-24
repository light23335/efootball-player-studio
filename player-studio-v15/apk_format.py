"""Preserve original APK data alignment; replace entries and sign with APK v2.

Uses the Android APK Signature Scheme v2 layout. It never attempts to reuse an
invalid signature or impersonate the original APK signer. Private keys stay in
the local data directory and are never included in player or delta packages.
"""
from pathlib import Path
import copy
import datetime
import hashlib
import os
import shutil
import struct
import zipfile
import zlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

MAGIC=b'APK Sig Block 42'
V2_ID=0x7109871a
RSA_SHA256=0x0103


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


def replace_entries(source,output,replacements):
    """Retain original local records and offsets, append only changed entries.

    Native libraries retain their original 4/16-KiB alignment. Central directory
    offsets use unsigned 32-bit fields, including offsets above Python's default
    2-GiB ZIP64 threshold. Android APK v2 does not accept a ZIP64 end record.
    """
    source=Path(source);output=Path(output)
    if output.exists() or source.absolute()==output.absolute():raise ValueError('Output APK must be a new file')
    meta=layout(source)
    with zipfile.ZipFile(source) as z:
        old={i.filename:i for i in z.infolist()}
        if len(old)!=len(z.infolist()):raise ValueError('Source APK has duplicate ZIP entries')
        # Preserve all original data byte-for-byte, including native alignment.
        entries=[copy.copy(i) for i in z.infolist() if i.filename not in replacements]
        comment=z.comment
    with source.open('rb') as src,output.open('xb') as dst:
        copy_bytes(src,dst,meta['data_end'])
        for name,data in replacements.items():
            if name.startswith('/') or '\\' in name or '..' in name.split('/'):
                raise ValueError('Invalid replacement path')
            item=copy.copy(old[name]) if name in old else zipfile.ZipInfo(name,(2026,1,1,0,0,0))
            item.flag_bits&=~8
            item.header_offset=dst.tell();item.file_size=len(data);item.CRC=zlib.crc32(data)&0xffffffff
            if item.compress_type==zipfile.ZIP_DEFLATED:
                encoder=zlib.compressobj(9,zlib.DEFLATED,-15);compressed=encoder.compress(data)+encoder.flush()
            elif item.compress_type==zipfile.ZIP_STORED:compressed=data
            else:raise ValueError('Unsupported APK entry compression')
            item.compress_size=len(compressed)
            # New entries have no ZIP64/alignment extra field; unchanged entries
            # keep their original data and extra fields.
            item.extra=b''
            dst.write(item.FileHeader(zip64=False));dst.write(compressed);entries.append(item)
        central=dst.tell()
        if len(entries)>=65535:raise ValueError('Too many APK entries for non-ZIP64 format')
        for item in entries:
            if max(item.file_size,item.compress_size,item.header_offset)>=0xffffffff:
                raise ValueError('APK exceeds the unsigned 32-bit ZIP format')
            name,flags=item._encodeFilenameFlags()
            y,mo,day,h,mi,s=item.date_time
            dos_time=h<<11|mi<<5|s//2;dos_date=(y-1980)<<9|mo<<5|day
            fields=(0x02014b50,item.create_version|(item.create_system<<8),item.extract_version,flags,item.compress_type,
                    dos_time,dos_date,item.CRC,item.compress_size,item.file_size,len(name),len(item.extra),len(item.comment),
                    0,item.internal_attr,item.external_attr,item.header_offset)
            dst.write(struct.pack('<I6H3I5H2I',*fields));dst.write(name);dst.write(item.extra);dst.write(item.comment)
        central_size=dst.tell()-central
        if dst.tell()+22+len(comment)>=0xffffffff:raise ValueError('APK is too large')
        dst.write(struct.pack('<I4H2IH',0x06054b50,0,0,len(entries),len(entries),central_size,central,len(comment)))
        dst.write(comment)
    return layout(output)


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


def sign_v2(unsigned,output,key,certificate):
    unsigned=Path(unsigned);output=Path(output)
    if output.exists() or unsigned.absolute()==output.absolute():raise ValueError('Signed output must be a new file')
    meta=layout(unsigned)
    if meta['data_end']!=meta['central']:raise ValueError('Expected unsigned intermediate APK')
    digest=content_digest(unsigned,meta)
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
    end=bytearray(meta['end_record']);struct.pack_into('<I',end,16,meta['central']+len(block))
    with unsigned.open('rb') as src,output.open('xb') as dst:
        copy_bytes(src,dst,meta['central']);dst.write(block)
        copy_bytes(src,dst,meta['central_size']);dst.write(end)
    return {'signer_sha256':hashlib.sha256(cert).hexdigest(),'content_digest':digest.hex(),'size':output.stat().st_size}


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
