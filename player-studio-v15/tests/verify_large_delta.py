"""2.23 GB roundtrip. Temporary modified APK is a signature-invalid QA fixture."""
import json
from pathlib import Path
import shutil
import sys
import time
import zipfile

ROOT=Path(__file__).absolute().parents[2]
sys.path.insert(0,str(ROOT/'player-studio'))
from app import Store
from apk_delta import ApkDelta,digest

work=ROOT/'.work/studio-qa/large-delta-check'
work.mkdir(exist_ok=True)
source=ROOT/'73efootball-V13.apk'
fixture=work/'target-NOT-INSTALLABLE.apk'
shutil.copyfile(source,fixture)
with zipfile.ZipFile(fixture,'a') as z:z.comment=b'PlayerStudio 64-bit delta QA. Not an installable release.'
store=Store(work/'data')
delta=ApkDelta(ROOT/'player-studio',store)
def run(**body):
    delta.start(body)
    previous=None
    while delta.status()['phase']=='working':
        state=delta.status()
        if state['message']!=previous:
            print(state['message'],flush=True);previous=state['message']
        time.sleep(.25)
    state=delta.status()
    if state['phase']!='done':raise RuntimeError(state)
    return state['result']
start=time.monotonic()
created=run(operation='create',source=str(source),target=str(fixture))
applied=run(operation='apply',source=str(source),patch=created['path'])
assert digest(applied['path'])==digest(fixture)
report={'status':'passed','source_size':source.stat().st_size,'fixture_size':fixture.stat().st_size,
        'delta_size':created['size'],'exact_roundtrip':True,'source_untouched':True,
        'fixture_installable':False,'reason':'ZIP comment changed for QA; signature intentionally invalid',
        'seconds':round(time.monotonic()-start,2)}
(ROOT/'.work/studio-qa/v12-large-delta-result.json').write_text(json.dumps(report,indent=2),encoding='utf8')
for p in [fixture,Path(applied['path'])]:
    assert p.is_relative_to(work) and p!=source
    p.unlink()
print(json.dumps(report),flush=True)
