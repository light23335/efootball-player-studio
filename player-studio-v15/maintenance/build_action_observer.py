"""Build the version-checked, observation-only V17 action journal hooks."""
from pathlib import Path
import sys,json,hashlib,argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from skill_hook_ir import Hooks
from action_observer import add_observer,add_shot_observation
from action_trace import SCHEMA

REVISION='v17-player-actions-v5-native-gameactor-index'
ENGINE_SHA='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'

def build(engine,release=False,ai=False):
    if hashlib.sha256(engine).hexdigest()!=ENGINE_SHA:raise ValueError('Action observer requires audited original V17')
    b=Hooks(engine)
    if ai:
        from build_ai_cut_in_shots import add_ai_cut_in_shots
        add_ai_cut_in_shots(b)
    add_observer(b);add_shot_observation(b,ai)
    bundle=b.bundle('studio_player_action_observer',b.rows+b.helpers)
    bundle['action_trace_schema']=SCHEMA
    marker=next(i for i,row in enumerate(b.rows+b.helpers)if row['name']=='studio_trace_actor')
    # Bundle writable labels are namespaced by row index, not an assumed
    # ordering (the AI variant has its own existing preference caches).
    needle='data_'+str(marker)+'_trace_ring'
    keys=list(bundle['writable']);bundle['action_trace_writable_index']=keys.index(needle)
    return {'revision':REVISION,'production_ready':release,'engine_sha256':ENGINE_SHA,
            'bundles':[bundle],'hooks':b.rows,'schema':SCHEMA,
            'coverage':['both teams','native actor-state transitions','native motion selection attempts and outcomes',
                        'native and post-preference AI candidate classes (shot/pass/dribble)',
                        'movement position samples every 30 native ticks within an unchanged state',
                        'native and post-preference AI shot requests and shot power','effective Blitz/Low/Heavy flags',
                        'pre-filter hook counters and minimal unverified-identity diagnostics'],
            'limits':['unknown action IDs remain raw','duplicate identical motion attempts within one frame suppressed',
                      'bounded ring overruns and contention are reported','motion selection success is not a proof the clip was finally played']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--engine',required=True);p.add_argument('--output',required=True);p.add_argument('--release',action='store_true');a=p.parse_args()
    engine=Path(a.engine).read_bytes();result=build(engine,a.release)
    result['ai_bundles']=build(engine,a.release,True)['bundles']
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf8')
    print('action observer hooks',len(result['hooks']),'body',len(bytes.fromhex(result['bundles'][0]['body_hex'])))
