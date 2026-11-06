"""Bounded append-only native CustomStadiumAssetTableRow adapter (UE4.26)."""
import struct
from native_iostore import package_names,rename_package


def row_base(raw,names,h):
    """Cooked CompositeDataTables own their merged rows; parents are not rebuilt.

    The inspected composites prepend ParentTables (two null hard references)
    to the ordinary RowStruct. Retain that property and its imports verbatim.
    """
    base=h[13]+h[14]
    if h[12]-h[11]!=72:raise ValueError('球场资料表导出结构改变')
    if names[struct.unpack_from('<I',raw,base)[0]]=='ParentTables':
        size=struct.unpack_from('<I',raw,base+16)[0]
        if (names[struct.unpack_from('<I',raw,base+8)[0]]!='ArrayProperty' or
            names[struct.unpack_from('<I',raw,base+24)[0]]!='ObjectProperty' or raw[base+32]!=0 or
            size!=4+4*struct.unpack_from('<I',raw,base+33)[0]):
            raise ValueError('球场合并表 ParentTables 布局改变')
        base+=33+size
    if len(raw)<base+45 or names[struct.unpack_from('<I',raw,base)[0]]!='RowStruct':raise ValueError('球场资料表 RowStruct 不匹配')
    return base


def read(raw):
    names=package_names(raw);h=struct.unpack_from('<16I',raw);base=row_base(raw,names,h)
    if (h[12]-h[11])!=72:raise ValueError('球场对象表导出结构改变')
    # RowStruct object property, None, object GUID=false, row count.
    if len(raw)<base+45 or names[struct.unpack_from('<I',raw,base)[0]]!='RowStruct':raise ValueError('球场对象表头不匹配')
    count=struct.unpack_from('<I',raw,base+41)[0]
    if count>256 or base+45+count*79!=len(raw):raise ValueError('球场对象表行结构改变')
    rows={}
    for i in range(count):
        at=base+45+i*79;row=raw[at:at+79]
        if (names[struct.unpack_from('<I',row,8)[0]]!='Asset' or
            names[struct.unpack_from('<I',row,16)[0]]!='SoftObjectProperty' or
            struct.unpack_from('<I',row,24)[0]!=12 or row[32]!=0 or
            names[struct.unpack_from('<I',row,45)[0]]!='bLevel' or
            names[struct.unpack_from('<I',row,53)[0]]!='BoolProperty' or
            names[struct.unpack_from('<I',row,71)[0]]!='None'):
            raise ValueError('球场对象表属性结构改变')
        key=names[struct.unpack_from('<I',row,0)[0]]
        if key in rows:raise ValueError('球场对象表含重复编号')
        rows[key]={'bytes':row,'asset':names[struct.unpack_from('<I',row,33)[0]],'level':bool(row[69])}
    return names,h,base,rows


def append(raw,entries):
    names,h,base,old=read(raw)
    for ident,path in entries.items():
        if type(ident)is not int or not 1<=ident<=255 or not path.startswith('/Game/'):
            raise ValueError('自制球场对象编号或路径无效')
        if str(ident)in old and old[str(ident)]['asset']!=path+'.'+path.rsplit('/',1)[-1]:
            raise ValueError('球场对象编号已被当前内容包使用：'+str(ident))
    additions={k:p for k,p in entries.items() if str(k)not in old}
    if not additions:return raw,{'added':0,'reused':len(entries)}
    logical=names[h[0]&0x3fffffff]
    extra=[v for key,path in additions.items()for v in(str(key),path+'.'+path.rsplit('/',1)[-1])]
    data,_=rename_package(raw,logical,extra_names=extra)
    names,h,base,rows=read(data);out=bytearray(data)
    template=bytearray(next(v['bytes']for v in rows.values()if not v['level']))
    for key,path in sorted(additions.items()):
        row=bytearray(template)
        struct.pack_into('<II',row,0,names.index(str(key)),0)
        struct.pack_into('<II',row,33,names.index(path+'.'+path.rsplit('/',1)[-1]),0)
        out.extend(row)
    struct.pack_into('<I',out,base+41,len(rows)+len(additions))
    struct.pack_into('<Q',out,h[11]+8,struct.unpack_from('<Q',out,h[11]+8)[0]+79*len(additions))
    check=read(out)[3]
    if any(check[k]['bytes']!=v['bytes']for k,v in rows.items()):raise ValueError('原生球场对象行被意外修改')
    return bytes(out),{'added':len(additions),'reused':len(entries)-len(additions),'original_rows':len(rows)}


def read_groups(raw):
    """Inspected CustomStadiumAssetGroupTableRow: Name -> SoftObject map."""
    names=package_names(raw);h=struct.unpack_from('<16I',raw);base=row_base(raw,names,h)
    count=struct.unpack_from('<I',raw,base+41)[0];at=base+45;rows={}
    if count>256:raise ValueError('球场主题组过多')
    for _ in range(count):
        start=at;key=names[struct.unpack_from('<I',raw,at)[0]]
        if key in rows:raise ValueError('球场主题编号重复')
        if any(names[struct.unpack_from('<I',raw,at+off)[0]]!=name for off,name in ((8,'Assets'),(16,'MapProperty'),(32,'NameProperty'),(40,'SoftObjectProperty'))):raise ValueError('球场主题映射属性改变')
        size=struct.unpack_from('<I',raw,at+24)[0];removed,n=struct.unpack_from('<II',raw,at+49)
        if raw[at+48]!=0 or removed or n>64 or size!=8+20*n:raise ValueError('球场主题映射布局改变')
        values={};offsets={}
        for j in range(n):
            entry=at+57+j*20;member=names[struct.unpack_from('<I',raw,entry)[0]]
            if member in values or struct.unpack_from('<I',raw,entry+16)[0]:raise ValueError('球场主题引用不完整')
            values[member]=names[struct.unpack_from('<I',raw,entry+8)[0]];offsets[member]=entry+8-start
        at+=49+size
        if names[struct.unpack_from('<I',raw,at)[0]]!='None':raise ValueError('球场主题行结尾改变')
        at+=8;rows[key]={'bytes':raw[start:at],'assets':values,'offsets':offsets}
    if at!=len(raw):raise ValueError('球场主题表存在未识别尾部')
    return names,h,base,rows


def append_groups(raw,entries):
    """Append (ID, source-row, texture path), retaining every other prop."""
    names,h,base,old=read_groups(raw)
    for ident,(source,path)in entries.items():
        if type(ident)is not int or not 1<=ident<=255 or not path.startswith('/Game/'):raise ValueError('看台 TIFO 主题编号或路径无效')
        if str(ident)in old and old[str(ident)]['assets'].get('Choreography')!=path+'.'+path.rsplit('/',1)[-1]:raise ValueError('看台 TIFO 主题编号冲突')
        if str(source)not in old or 'Choreography'not in old[str(source)]['assets']:raise ValueError('所选入场主题没有看台 TIFO 载体')
    if not entries:return raw,{'added':0,'reused':0}
    extra=[v for k,(_,path)in entries.items()for v in(str(k),path+'.'+path.rsplit('/',1)[-1])]
    data,_=rename_package(raw,names[h[0]&0x3fffffff],extra_names=extra);names,h,base,rows=read_groups(data);out=bytearray(data);added=0
    updates={};changed=0
    for ident,(source,path)in sorted(entries.items()):
        template=rows[str(source)];row=bytearray(template['bytes']);struct.pack_into('<II',row,0,names.index(str(ident)),0)
        struct.pack_into('<II',row,template['offsets']['Choreography'],names.index(path+'.'+path.rsplit('/',1)[-1]),0)
        updates[str(ident)]=bytes(row)
    out=bytearray(data[:base+45])
    for key,row in rows.items():
        value=updates.pop(key,row['bytes']);changed+=value!=row['bytes'];out.extend(value)
    for value in updates.values():out.extend(value);added+=len(value)
    additions=len(updates)
    struct.pack_into('<I',out,base+41,len(rows)+additions);struct.pack_into('<Q',out,h[11]+8,struct.unpack_from('<Q',out,h[11]+8)[0]+len(out)-len(data))
    check=read_groups(out)[3]
    if any(check[k]['bytes']!=r['bytes']for k,r in rows.items()if k not in {str(i)for i in entries}):raise ValueError('原生入场主题被意外修改')
    for ident,(source,path)in entries.items():
        expected={**rows[str(source)]['assets'],'Choreography':path+'.'+path.rsplit('/',1)[-1]}
        if check[str(ident)]['assets']!=expected:raise ValueError('巨幅海报以外的默认套装部件不一致')
    return bytes(out),{'added':additions,'reused':len(entries)-additions,'updated':changed}
