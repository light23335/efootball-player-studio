"""Debug-only persistence check after the real Android document picker."""
from pathlib import Path
import json,time,zipfile

def run(home,native_dir,fixtures,operation):
    from android_backend import start
    import android_backend
    from java import jclass
    start(home,native_dir)
    if operation=='documents':
        snapshot=json.loads(str(jclass('com.playerstudio.editor.NativeFiles').descriptorSnapshot()))
        matches=[Path(p) for p in snapshot if p.endswith('/authorized-source.apk')]
        assert len(matches)==1,snapshot
        with zipfile.ZipFile(matches[0]) as archive:
            assert archive.read('proof')==b'player-studio-android-source-permission'
        return json.dumps({'saf_apk_permission_after_process_restart':'passed','bytes':matches[0].stat().st_size})
    assert operation=='companion'
    sources=json.loads(str(jclass('com.playerstudio.editor.QaBridge').originals(home)))
    worker=android_backend._server.native_package
    worker.start({'operation':'companion','companion':sources['companion']})
    deadline=time.monotonic()+1200
    while time.monotonic()<deadline:
        state=worker.status()
        if state['phase']!='working':break
        time.sleep(1)
    assert state['phase']=='done',state
    result=state['result'];assert result['signature']['verified_v2']
    return json.dumps({'android_companion_signing':'passed','bytes':result['size'],'signature':result['signature']})
