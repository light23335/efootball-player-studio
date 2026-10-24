"""Validate the public JNI console entry before queuing render settings."""
import json
from pathlib import Path
from native_fps import EngineMemory

def verify_display(engine,resources=None):
    p=(Path(resources) if resources else Path(__file__).parent/'resources')/'native-display.json'
    data=json.loads(p.read_text(encoding='utf8'));memory=EngineMemory(engine)
    try:
        if memory.read(data['address'],64).hex()!=data['expected_hex']:raise ValueError('此版本的游戏渲染设置接口发生变化，未写入分辨率')
    finally:memory.close()
    return {'jni_entry_verified':True,'method':'GameActivity.nativeConsoleCommand(String)','actual_render_resolution_measured':False}
