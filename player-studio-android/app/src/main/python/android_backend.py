"""Phone-local application host. No desktop or remote server is used."""
from pathlib import Path
import hashlib,json,logging,os,secrets,shutil,sys,tempfile,threading,time

_server=None
def start(home,native_dir):
    global _server
    if _server:return json.dumps({'port':_server.server_port,'url':_server.launch_url})
    home=Path(home);bundle=home/'bundle';sys._MEIPASS=str(bundle)
    os.environ['STUDIO_CODECS']=str(Path(native_dir)/'libstudio_codecs.so')
    from android_files import install
    install()
    data=home/'data';(data/'tmp').mkdir(parents=True,exist_ok=True);tempfile.tempdir=str(data/'tmp')
    logging.basicConfig(filename=data/'studio.log',level=logging.INFO,encoding='utf8')
    import app,apk_database,native_library,native_presets,native_package
    from android_library import AndroidLibrary,index_assets,android_movie
    from android_package import AndroidPackage,sign_v2_in_place
    from java import jclass
    native_files=jclass('com.playerstudio.editor.NativeFiles')
    installed_games=jclass('com.playerstudio.editor.InstalledGames')
    app.PLATFORM='android'
    app.open_update_action=lambda url:bool(installed_games.openReleasePage(url))
    def open_export_action(store,name):
        from workspace_tools import export_file
        path=export_file(store,name)
        if path.suffix.lower()!='.apk':raise ValueError('只有 APK 可以直接安装；其他文件请使用保存')
        installed_games.validateInstall(str(path))
        return {'opened':True,'action':str(native_files.install(str(path)))}
    app.open_export_action=open_export_action
    app.dialog=lambda kind='open',category='project',initial='':str(native_files.pick(kind,category,initial)) or None
    app.NativeLibrary=AndroidLibrary;native_library.NativeLibrary=AndroidLibrary
    app.NativePackage=AndroidPackage;native_package.sign_v2=sign_v2_in_place
    apk_database.index_assets=index_assets
    native_library.convert_movie=android_movie;native_presets.convert_movie=android_movie
    BaseServer=app.StudioServer
    BaseHandler=app.Handler
    class AndroidHandler(BaseHandler):
        def do_POST(self):
            from urllib.parse import urlsplit,unquote,quote
            if urlsplit(self.path).path!='/api/android-export':return super().do_POST()
            if not self.authenticated():return self.send({'error':'会话无效'},403)
            origin=self.headers.get('Origin')
            if origin and origin!='http://127.0.0.1:'+str(self.server.server_port):return self.send({'error':'来源不匹配'},403)
            temporary=None
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=128*1024*1024:raise ValueError('图片或模型导出大小须在 128 MB 以内')
                name=unquote(self.headers.get('X-Studio-Filename','export.bin'))
                if len(name)>180 or any(c in name for c in '/\\\x00\r\n') or name in ('.','..'):raise ValueError('导出文件名无效')
                folder=self.server.store.root/'exports';folder.mkdir(exist_ok=True)
                target=folder/(secrets.token_hex(5)+'-'+name);temporary=target.with_suffix(target.suffix+'.part')
                remaining=size
                with temporary.open('xb') as out:
                    while remaining:
                        chunk=self.rfile.read(min(1024*1024,remaining))
                        if not chunk:raise ValueError('导出内容未完整传输')
                        out.write(chunk);remaining-=len(chunk)
                temporary.replace(target)
                return self.send({'url':'/exports/'+quote(target.name),'filename':name})
            except Exception as exc:
                if temporary:temporary.unlink(missing_ok=True)
                return self.send({'error':str(exc)},400)
    app.Handler=AndroidHandler
    class LocalServer(BaseServer):
        def __init__(self,address,store):
            super().__init__(address,store)
            self.home=home;self.use_resources(apk_database.active_resources(app.RESOURCE,store.root))
    server=LocalServer(('127.0.0.1',0),app.Store(data))
    server.installed_sources=lambda:json.loads(str(installed_games.scan()))
    server.launch_url='http://127.0.0.1:'+str(server.server_port)+'/?token='+server.token
    _server=server
    threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.3},daemon=True).start()
    return json.dumps({'port':server.server_port,'url':server.launch_url,'version':app.APP_VERSION})

def busy():
    if _server is None:return False
    return (_server.native_package.status()['phase']=='working' or _server.game_import.status()['phase']=='working'
            or _server.library.state['phase']=='preparing')

def work_status():
    if _server:
        for worker in (_server.native_package,_server.game_import):
            state=worker.status()
            if state['phase']=='working':return json.dumps({'busy':True,'message':state.get('message','本机任务进行中')})
        if _server.library.state['phase']=='preparing':return json.dumps({'busy':True,'message':_server.library.state.get('message','准备原版资源')})
    return json.dumps({'busy':False,'message':'本机编辑服务运行中'},ensure_ascii=False)

def stop():
    global _server
    if _server:
        _server.shutdown();_server.server_close();_server=None
