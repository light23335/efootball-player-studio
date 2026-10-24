"""Windows system HTTPS for update metadata; certificate validation stays enabled."""
import ctypes,os,urllib.error
from ctypes import wintypes as w
from urllib.parse import urlsplit

LIMIT=256*1024
def fetch(url,agent,timeout=8):
    if os.name!='nt':raise OSError('Windows HTTPS is unavailable on this platform')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='api.github.com' or parsed.username or parsed.password:raise ValueError('更新请求地址无效')
    api=ctypes.WinDLL('winhttp',use_last_error=True);handle=w.HANDLE
    def bind(name,result,args):
        fn=getattr(api,name);fn.restype=result;fn.argtypes=args;return fn
    open_=bind('WinHttpOpen',handle,[w.LPCWSTR,w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD])
    connect=bind('WinHttpConnect',handle,[handle,w.LPCWSTR,w.WORD,w.DWORD])
    request=bind('WinHttpOpenRequest',handle,[handle,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,ctypes.POINTER(w.LPCWSTR),w.DWORD])
    send=bind('WinHttpSendRequest',w.BOOL,[handle,w.LPCWSTR,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,ctypes.c_size_t])
    receive=bind('WinHttpReceiveResponse',w.BOOL,[handle,w.LPVOID])
    headers=bind('WinHttpQueryHeaders',w.BOOL,[handle,w.DWORD,w.LPCWSTR,w.LPVOID,ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD)])
    available=bind('WinHttpQueryDataAvailable',w.BOOL,[handle,ctypes.POINTER(w.DWORD)])
    read=bind('WinHttpReadData',w.BOOL,[handle,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)])
    timeouts=bind('WinHttpSetTimeouts',w.BOOL,[handle,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int])
    close=bind('WinHttpCloseHandle',w.BOOL,[handle]);opened=[]
    def checked(value):
        if not value:raise OSError(ctypes.get_last_error(),'Windows HTTPS 请求失败')
        return value
    try:
        session=checked(open_(agent,4,None,None,0));opened.append(session)
        checked(timeouts(session,*([int(timeout*1000)]*4)))
        connection=checked(connect(session,parsed.hostname,443,0));opened.append(connection)
        req=checked(request(connection,'GET',parsed.path+('?' +parsed.query if parsed.query else ''),None,None,None,0x00800000));opened.append(req)
        checked(send(req,'Accept: application/vnd.github+json\r\nX-GitHub-Api-Version: 2022-11-28\r\n',0xffffffff,None,0,0,0));checked(receive(req,None))
        status=w.DWORD();size=w.DWORD(ctypes.sizeof(status));checked(headers(req,19|0x20000000,None,ctypes.byref(status),ctypes.byref(size),None))
        if status.value!=200:raise urllib.error.HTTPError(url,status.value,'Windows HTTPS HTTP '+str(status.value),None,None)
        result=bytearray()
        while True:
            count=w.DWORD();checked(available(req,ctypes.byref(count)))
            if not count.value:break
            if len(result)+count.value>LIMIT:raise ValueError('更新说明超过大小限制')
            buffer=ctypes.create_string_buffer(count.value);got=w.DWORD();checked(read(req,buffer,count.value,ctypes.byref(got)))
            if not got.value:break
            result.extend(buffer.raw[:got.value])
        return bytes(result)
    finally:
        for item in reversed(opened):close(item)
