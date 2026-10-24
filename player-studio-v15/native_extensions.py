"""Small checked A64 adapters for cloned native Link-up condition records."""
import struct


def words(*values):return struct.pack('<'+'I'*len(values),*values)


def mappings(routes,register):
    out=bytearray()
    for row in sorted(routes,key=lambda r:r['id']):
        ident,original=row['id'],row['template_id']
        if type(ident) is not int or not 256<=ident<512 or type(original) is not int or not 1<=original<=32:
            raise ValueError('心有灵犀类型映射超出已核对范围')
        # cmp wN,#id; b.ne +8; mov wN,#original.
        out.extend(words(0x7100001f|(ident<<10)|(register<<5),0x54000041,0x52800000|(original<<5)|register))
    return out


def link_hooks(routes,engine,info):
    if not routes:return []
    routes=list({r['id']:r for r in routes}.values())
    result=[]
    for name,site in info['hooks'].items():
        engine.seek(site['file_offset'])
        if engine.read(64).hex()!=site['expected_hex']:raise ValueError('此版本的心有灵犀接口发生变化，未写入')
        if name=='effect':
            body=mappings(routes,0)
            body.extend(words(0x7100801f)) # displaced cmp w0,#32
            body.extend(bytes.fromhex('1f2003d5')*((-len(body)%8)//4))
            at=len(body);body.extend(words(0x58000050,0xd61f0200));body.extend(bytes(8))
            fixes=[[at+8,site['address']+4]]
        elif name=='label':
            body=bytearray(words(0xb9402fe8)) # ldr w8,[sp,#44]
            body.extend(mappings(routes,8));body.extend(words(0xb9002fe8))
            body.extend(bytes.fromhex('1f2003d5')*((-len(body)%8)//4))
            at=len(body)
            body.extend(words(0x58000088,0x580000b0,0xd61f0200,0xd503201f));body.extend(bytes(16))
            fixes=[[at+16,0xcd4000],[at+24,site['address']+4]]
        else:raise ValueError('未知的心有灵犀接口')
        result.append({'name':'coach-link-'+name,'address':site['address'],'expected_hex':site['expected_hex'],
                       'body_hex':body.hex(),'absolute_fixups':fixes})
    return result
