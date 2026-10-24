"""Run the inspected worker against isolated bytes, never process memory."""
import copy,struct,types,ctypes as scalar_types
from personal_binding import _BindingCtypes


class Complete(BaseException):pass


def run(function,payload,engine):
 base=0x7000000000;page=base+0x6000000;areas={}
 phoff=struct.unpack_from('<Q',engine,32)[0];entry_size,count=struct.unpack_from('<HH',engine,54)
 for n in range(count):
  kind,flags,offset,virtual,physical,file_size,memory_size,alignment=struct.unpack_from('<IIQQQQQQ',engine,phoff+n*entry_size)
  if kind==1:areas[base+virtual]=bytearray(engine[offset:offset+file_size])+bytearray(memory_size-file_size)
 areas[page]=bytearray(8192)
 protections=[];flushes=[];reports=[];buffers={};next_buffer=0x9000000000;next_extension=0x8000000000
 def locate(address,size):
  for start,data in reversed(list(areas.items())):
   if start<=address and address+size<=start+len(data):return data,address-start
  raise AssertionError('unmapped simulated range: '+hex(address)+' '+str(size))
 def read(address,size):
  data,at=locate(address,size);return bytes(data[at:at+size])
 def write(address,value):
  data,at=locate(address,len(value));data[at:at+len(value)]=value
 def scalar(size):
  class Cell:
   def __init__(self,address):self.address=address
   @classmethod
   def from_address(cls,address):return cls(address)
   @property
   def value(self):return int.from_bytes(read(self.address,size),'little')
   @value.setter
   def value(self,value):write(self.address,value.to_bytes(size,'little'))
  return Cell
 def mmap(address,size,*args):
  nonlocal next_extension
  result=next_extension;next_extension+=size+0x10000;areas[result]=bytearray(size);return result
 def mprotect(address,size,mode):locate(address,size);protections.append((address,size,mode));return 0
 libc=types.SimpleNamespace(mmap=mmap,mprotect=mprotect)
 class Ctypes:
  c_void_p=scalar_types.c_void_p;c_size_t=scalar_types.c_size_t;c_int=scalar_types.c_int;c_long=scalar_types.c_long
  c_uint32=scalar(4);c_uint64=scalar(8)
  def create_string_buffer(self,raw):
   nonlocal next_buffer
   value=bytearray(raw if isinstance(raw,int) else raw+b'\0');areas[next_buffer]=value;buffers[id(value)]=next_buffer;next_buffer+=len(value)+0x10000;return value
  def addressof(self,value):return buffers[id(value)]
  def CDLL(self,*args,**kwargs):return libc
  def get_errno(self):return 0
  def memmove(self,destination,source,size):
   value=read(source,size) if isinstance(source,int) else bytes(source[:size]);write(destination,value);return destination
  def string_at(self,address,size):return read(address,size)
  def CFUNCTYPE(self,*args):
   def address(value):
    def flush(start,end):flushes.append((start,end))
    return flush
   return address
 def report(value):
  reports.append(copy.deepcopy(value))
  if value['status'] in ('binding_installed','not_applied'):raise Complete()
 def forbidden(*args):raise AssertionError('unexpected native allocation path')
 code=next(c for c in function.__code__.co_consts if isinstance(c,types.CodeType) and c.co_name=='worker')
 values={'PAYLOAD':payload,'Path':lambda path:types.SimpleNamespace(read_text=lambda:'simulated maps'),'ProcessMemory':lambda rows:types.SimpleNamespace(read=read),'_allocate_near':forbidden,'_api':lambda:libc,'_resident':[],
         'branch_word':lambda source,target:0x14000000|(((target-source)//4)&0x3ffffff),'ctypes':_BindingCtypes(Ctypes(),payload),'library_base':lambda rows:base,
         'os':types.SimpleNamespace(getpid=lambda:123,sysconf=lambda name:4096),'parse_maps':lambda text:[], 'report':report,'struct':struct,'time':types.SimpleNamespace(sleep=lambda seconds:None)}
 worker=types.FunctionType(code,function.__globals__,closure=tuple(types.CellType(values[k]) for k in code.co_freevars))
 # Return the address our allocator stub must use; all hook writes are local.
 try:worker()
 except Complete:pass
 assert reports and reports[-1]['status'] in ('binding_installed','not_applied'),reports
 patched=0
 for hook in payload['hooks']:
  expected=values['branch_word'](base+hook['address'],page+hook['offset'])
  if int.from_bytes(read(base+hook['address'],4),'little')==expected:patched+=1
 return {'status':reports[-1]['status'],'error':reports[-1].get('error'),'patched_hooks':patched,'total_hooks':len(payload['hooks']),'protections':len(protections),'cache_flushes':len(flushes),'root_address':page}
