"""Read and validate the original FPS interface without executing APK modules."""
from pathlib import Path
import struct,types
from apk_literals import module_reader,literal_assignments
from personal_runtime import prepare_fps160

def fps_module(apk):
    code=module_reader(apk)('fps120_runtime')
    keys={'PAYLOAD','TABLE_ADDRESS','ENGINE_ENUM_ADDRESS','MAILBOX_LITERAL','MAILBOX_SIZE','MAILBOX_DESIRED','MAILBOX_ALLOW','MAILBOX_SEQ','USER_FPS_ENUMS','FPS_SETTING_OFFSET','SETTINGS_SINGLETON','ENGINE_FPS_SETTER'}
    namespace=literal_assignments(code,keys)
    namespace.update(__name__='studio_fps_preflight',struct=struct,_started=False,
                     BUILD_NOTE=bytes.fromhex('040000001000000003000000474e55009068c18632a8023ad3e9c6faf3fe92d9'))
    for child in code.co_consts:
        if isinstance(child,types.CodeType) and child.co_name!='ProcessMemory':
            namespace[child.co_name]=types.FunctionType(child,namespace)
    module=types.ModuleType('studio_fps_preflight');module.__dict__.update(namespace)
    # Original function globals must see the same template and wrappers.
    for name,value in list(vars(module).items()):
        if isinstance(value,types.FunctionType):setattr(module,name,types.FunctionType(value.__code__,vars(module)))
    return module

class EngineMemory:
    def __init__(self,path):
        self.owns=not hasattr(path,'read');self.file=Path(path).open('rb') if self.owns else path
        self.file.seek(0);head=self.file.read(64)
        if head[:6]!=b'\x7fELF\x02\x01':raise ValueError('160 帧需要 ARM64 ELF 引擎')
        offset=struct.unpack_from('<Q',head,32)[0];size,count=struct.unpack_from('<HH',head,54);self.loads=[]
        for n in range(count):
            self.file.seek(offset+size*n)
            kind,flags,position,address,_,length,memory,_=struct.unpack('<IIQQQQQQ',self.file.read(56))
            if kind==1:self.loads.append((address,position,length,memory,flags))
    def region(self,address,length):
        for start,position,available,memory,flags in self.loads:
            if start<=address and address+length<=start+available:
                return {'start':start,'end':start+memory,'permissions':('r' if flags&4 else '-')+('w' if flags&2 else '-')+('x' if flags&1 else '-')+'p','offset':position,'path':'/libUE4.so'}
        raise ValueError('160 帧接口不在可读取引擎映射中')
    def read(self,address,length):
        row=self.region(address,length);self.file.seek(row['offset']+address-row['start']);return self.file.read(length)
    def close(self):
        if self.owns:self.file.close()

def verify_fps160(apk,engine,target=160):
    module=fps_module(apk);result=prepare_fps160(module,target);memory=EngineMemory(engine)
    try:module.validate(memory,0)
    finally:memory.close()
    return dict(result,native_hooks_verified=len(module.PAYLOAD['hooks']),engine_instructions_verified=True)
