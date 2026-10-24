"""Small lossless AXML editor for package identity and package visibility."""
import struct

ANDROID='http://schemas.android.com/apk/res/android'
NONE=0xffffffff

class Manifest:
 def __init__(self,raw):
  if len(raw)<8 or struct.unpack_from('<HH',raw)!=(3,8) or struct.unpack_from('<I',raw,4)[0]!=len(raw):raise ValueError('Android 清单格式无效')
  self.chunks=[];self.strings=[];at=8;self.pool=None
  while at<len(raw):
   kind,header,size=struct.unpack_from('<HHI',raw,at)
   if size<header or at+size>len(raw):raise ValueError('Android 清单区块无效')
   part=bytearray(raw[at:at+size]);self.chunks.append(part)
   if kind==1:
    if self.pool is not None:raise ValueError('Android 清单字符串池不唯一')
    self.pool=len(self.chunks)-1;count,styles,flags,start,style_start=struct.unpack_from('<5I',part,8)
    self.pool_meta=(header,styles,flags,bytes(part[header+count*4:header+(count+styles)*4]),bytes(part[style_start:]) if style_start else b'')
    def length(pos,utf8):
     if utf8:
      n=part[pos];return (((n&127)<<8)|part[pos+1],pos+2) if n&128 else (n,pos+1)
     n=struct.unpack_from('<H',part,pos)[0];return (((n&32767)<<16)|struct.unpack_from('<H',part,pos+2)[0],pos+4) if n&32768 else (n,pos+2)
    for i in range(count):
     pos=start+struct.unpack_from('<I',part,header+i*4)[0];n,pos=length(pos,bool(flags&256))
     if flags&256:n,pos=length(pos,True);codec='utf8'
     else:n*=2;codec='utf-16le'
     self.strings.append(bytes(part[pos:pos+n]).decode(codec))
   at+=size
  if self.pool is None:raise ValueError('Android 清单缺少字符串池')
 def string(self,index):return self.strings[index] if index!=NONE else None
 def index(self,value):
  try:return self.strings.index(value)
  except ValueError:self.strings.append(value);return len(self.strings)-1
 def nodes(self):
  for n,part in enumerate(self.chunks):
   if struct.unpack_from('<H',part)[0]!=0x102:continue
   ns,name,start,size,count=struct.unpack_from('<IIHHH',part,16);attrs=[]
   for i in range(count):
    pos=16+start+i*size;space,key,raw=struct.unpack_from('<III',part,pos);kind=part[pos+15];value=struct.unpack_from('<I',part,pos+16)[0]
    attrs.append({'position':pos,'namespace':self.string(space),'name':self.string(key),'type':kind,'data':value,'value':self.string(value) if kind==3 else value,'raw':self.string(raw)})
   yield n,self.string(name),attrs
 def set_string(self,node,attr,value):
  part=self.chunks[node];index=self.index(value);pos=attr['position'];struct.pack_into('<I',part,pos+8,index);struct.pack_into('<HBBI',part,pos+12,8,0,3,index)
 def info(self):
  out={'package':None,'version_code':0,'version_name':'','authorities':[]}
  for n,name,attrs in self.nodes():
   values={a['name']:a['value'] for a in attrs}
   if name=='manifest':out.update(package=values.get('package'),version_code=values.get('versionCode',0),version_name=values.get('versionName',''))
   if name=='provider' and 'authorities' in values:out['authorities'].append(values['authorities'])
  return out
 def clone(self,package,label,aliases):
  old=self.info()['package']
  if not isinstance(old,str):raise ValueError('清单缺少包名')
  if any(a['name']=='sharedUserId' for _,name,attrs in self.nodes() if name=='manifest' for a in attrs):raise ValueError('此 APK 使用共享 UID，不能安全生成共存版')
  replacements={old:package,**aliases}
  for n,name,attrs in list(self.nodes()):
   for a in attrs:
    value=a['value']
    if not isinstance(value,str):continue
    if name=='manifest' and a['name']=='package':self.set_string(n,a,package);continue
    if a['name'] in ('name','targetActivity','backupAgent','appComponentFactory') and name in ('application','activity','activity-alias','service','receiver','provider','instrumentation'):
     if value.startswith('.'):self.set_string(n,a,old+value)
     elif '.' not in value:self.set_string(n,a,old+'.'+value)
     continue
    if a['name'] in ('authorities','permission','readPermission','writePermission') or a['name']=='name' and name in ('permission','uses-permission','package','action'):
     for before,after in replacements.items():value=value.replace(before,after)
     if value!=a['value']:self.set_string(n,a,value)
   if name=='application':
    label_attr=next((a for a in attrs if a['name']=='label'),None)
    if label_attr:self.set_string(n,label_attr,label)
  return old
 def add_queries(self,packages,launcher=False):
  def start(name,attributes=()):
   part=bytearray(struct.pack('<HHIII',0x102,16,36+20*len(attributes),0,NONE)+struct.pack('<IIHHHHHH',NONE,self.index(name),20,20,len(attributes),0,0,0))
   for key,value in attributes:part.extend(struct.pack('<IIIHBBI',self.index(ANDROID),self.index(key),self.index(value),8,0,3,self.index(value)))
   return part
  def end(name):return bytearray(struct.pack('<HHIIIII',0x103,16,24,0,NONE,NONE,self.index(name)))
  entries=[start('queries')]
  for package in packages:entries.extend([start('package',[('name',package)]),end('package')])
  if launcher:entries.extend([start('intent'),start('action',[('name','android.intent.action.MAIN')]),end('action'),start('category',[('name','android.intent.category.LAUNCHER')]),end('category'),end('intent')])
  entries.append(end('queries'))
  at=next(n for n,name,attrs in self.nodes() if name=='application');self.chunks[at:at]=entries
 def bytes(self):
  header,styles,flags,style_offsets,style_data=self.pool_meta;utf8=bool(flags&256);data=bytearray();offsets=[]
  def length(n):
   if utf8:return bytes([n]) if n<128 else bytes([128|(n>>8),n&255])
   return struct.pack('<H',n) if n<32768 else struct.pack('<HH',0x8000|(n>>16),n&65535)
  for value in self.strings:
   offsets.append(len(data));units=len(value.encode('utf-16le'))//2
   if utf8:
    encoded=value.encode('utf8');data.extend(length(units)+length(len(encoded))+encoded+b'\0')
   else:data.extend(length(units)+value.encode('utf-16le')+b'\0\0')
  data.extend(bytes((-len(data))%4));start=header+4*(len(offsets)+styles)
  part=bytearray(self.chunks[self.pool][:header]);struct.pack_into('<I',part,4,start+len(data)+len(style_data));struct.pack_into('<I',part,8,len(offsets));struct.pack_into('<III',part,16,flags&~1,start,start+len(data) if style_data else 0)
  part.extend(struct.pack('<'+'I'*len(offsets),*offsets)+style_offsets+data+style_data)
  chunks=list(self.chunks);chunks[self.pool]=part;body=b''.join(chunks);return struct.pack('<HHI',3,8,len(body)+8)+body
