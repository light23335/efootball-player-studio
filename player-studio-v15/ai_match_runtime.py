"""Process-local bridge between prepared opponents and native match snapshots.

The native callback owns engine calls. This worker uses only a bounded shared
buffer and writes per-entry diagnostics. Automatic coaching is gated by ALL
native capability proofs plus a verified state decoder; absent proofs give a
read-only observer, never a guessed interpretation of native flags/periods.
"""
import copy
import hashlib
import json
import logging
import math
import os
import re
import secrets
import struct
import threading
from pathlib import Path

from ai_match_channel import read_snapshot,encode_command,publish
from ai_match_manager import Manager
from ai_match_state import decode_normal,decode_match

REQUIRED_PROOFS=('automatic_execution_verified','state_decoder_verified','entry_binding_verified',
                 'legal_windows_verified','emergency_reconciliation_verified')
_LOCK=threading.RLock()
_CHANNELS=[]
_ACTIVE=None


def signature(spec):
    # JSON persistence turns integer mapping keys into strings; retries after
    # that round trip must not silently create a new native epoch.
    normalized=json.loads(json.dumps(spec,separators=(',',':')))
    return hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Bridge:
    def __init__(self,buffer,offset,layout,fence,proof=None,decoder=None):
        if type(offset) is not int or offset<0 or offset%16:
            raise ValueError('Invalid coaching buffer offset')
        self.view=memoryview(buffer).cast('B')
        if offset+32768>len(self.view):raise ValueError('Coaching buffer is incomplete')
        if layout.get('bus_bytes_used',0)>32768 or layout.get('command_bytes')!=440 or layout.get('snapshot_bytes')!=4880:
            raise ValueError('Unsupported coaching channel layout')
        self.offset=offset;self.layout=copy.deepcopy(layout);self.fence=fence
        self.proof=copy.deepcopy(proof or {});self.decoder=decoder
        self.lock=threading.RLock();self.wake=threading.Event();self.thread=None
        self.spec=None;self.root=None;self.spec_hash=None;self.manager=None;self.external_log=None
        self.sequence=0;self.epoch=0;self.last_snapshot=0;self.last_log=None;self.failed=None
        self.last_request=None;self.last_diagnostic=None
        self.checkpoint_key=None;self.recovering=False
        self.execute=bool(callable(decoder) and all(self.proof.get(k) is True for k in REQUIRED_PROOFS))

    def read(self,at,size):
        if type(at) is not int or type(size) is not int or at<0 or size<0 or at+size>32768:
            raise ValueError('Coaching read outside shared buffer')
        return bytes(self.view[self.offset+at:self.offset+at+size])

    def write(self,at,data):
        if type(at) is not int or at<0 or at+len(data)>32768:
            raise ValueError('Coaching write outside shared buffer')
        self.view[self.offset+at:self.offset+at+len(data)]=data

    def word(self,name,value):self.write(self.layout[name],struct.pack('<I',value))

    def log(self,event,payload):
        if self.root is None:return
        # Entry IDs are data, never used as filesystem path components. The
        # optional external mirror belongs only to an explicit diagnostic APK.
        name=hashlib.sha256(self.spec['entry_id'].encode()).hexdigest()[:32]
        record={'event':event,'entry_id':self.spec['entry_id'],'game_id':self.spec['game_id'],
                'epoch':self.epoch,**payload}
        folders=[self.root/'outputs/efootball/ai-coaching']
        if self.external_log is not None:folders.append(self.external_log)
        for folder in folders:
            try:
                folder.mkdir(parents=True,exist_ok=True)
                path=folder/(name+'.jsonl')
                if path.exists() and path.stat().st_size>8*1024*1024:
                    path.replace(path.with_suffix('.jsonl.1'))
                with path.open('a',encoding='utf8') as out:
                    out.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
            except (OSError,ValueError,TypeError):
                logging.getLogger(__name__).warning('AI coaching diagnostic write failed',exc_info=True)

    def checkpoint_path(self):
        return self.root/'outputs/efootball/ai-coaching-state'/(
            hashlib.sha256(self.spec['entry_id'].encode()).hexdigest()+'.json')

    def restore_policy(self):
        """Only exact-entry state is reusable. Never replay an old transport request."""
        if not self.execute:return
        try:
            path=self.checkpoint_path()
            if path.stat().st_size>1024*1024:return
            row=json.loads(path.read_text('utf8'))
            if (row.get('format')!=1 or row.get('closed') or
                row.get('spec_sha256')!=self.spec_hash or
                row.get('entry_id')!=self.spec['entry_id'] or
                row.get('game_id')!=self.spec['game_id']):return
            old=row['state'];state=copy.deepcopy(self.manager.state)
            if old['mode'] not in ('base','chase','protect','last_push'):return
            profile_id=old.get('profile_id')
            import ai_tactical_profiles as templates
            if profile_id not in {p['id']for p in self.spec['profiles']+templates.profiles()}:return
            if type(old['next_id']) is not int or not 1<=old['next_id']<2**63:return
            for key in ('last_tactic_minute','last_sub_minute','last_evaluation_minute','elapsed_minute'):
                value=old[key]
                if type(value) not in (int,float) or not math.isfinite(value) or not -100<=value<=1500:return
                state[key]=value
            for key in ('used_out','previous_on_field'):
                value=old[key]
                if (not isinstance(value,list) or len(set(value))!=len(value) or
                    any(type(i) is not int or not 0<=i<23 for i in value)):return
                state[key]=value
            clock=old.get('last_clock')
            if clock is not None and (not isinstance(clock,list) or len(clock)!=2 or
                type(clock[0]) is not int or not 0<=clock[0]<=10 or
                type(clock[1]) not in (int,float) or not math.isfinite(clock[1]) or not 0<=clock[1]<=150):return
            rebuild=old.get('rebuild_due',False)
            if type(rebuild) is not bool:return
            state.update(mode=old['mode'],profile_id=profile_id,next_id=old['next_id'],last_clock=clock,rebuild_due=rebuild)
            level=old.get('attack_level')
            if type(level)is int and 0<=level<=4:state['attack_level']=level
            # The new bridge owns a new native epoch. It cannot acknowledge,
            # cancel or resubmit the old epoch's queued command. First observe
            # the actual native lineup; pending native emergencies keep control.
            state['journal']=[r for r in old.get('journal',[])[-127:] if isinstance(r,dict)]
            self.manager=Manager(self.spec,state);self.recovering=True
            pending=old.get('pending')
            self.manager.record('restore_awaiting_native',discarded_pending_id=
                pending.get('id') if isinstance(pending,dict) else None)
            self.log('policy_restore_waiting',{'pending_command_will_not_be_replayed':True})
        except (OSError,ValueError,TypeError,KeyError):
            return

    def save_policy(self,snapshot=None,closed=False,force=False):
        if not self.execute:return
        state=self.manager.state
        key=(len(state['journal']),state['next_id'],
             json.dumps(state['pending'],sort_keys=True),
             int(state['elapsed_minute']*2),closed)
        if key==self.checkpoint_key and not force:return
        row={'format':1,'entry_id':self.spec['entry_id'],'game_id':self.spec['game_id'],
             'spec_sha256':self.spec_hash,'closed':closed,'state':state}
        if snapshot is not None:
            row['last_native']={k:snapshot.get(k) for k in
                ('sequence','period','minute','score','on_field','substitutions_left','windows_left')}
        path=self.checkpoint_path();path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf8') as out:
            json.dump(row,out,ensure_ascii=False,separators=(',',':'));out.flush();os.fsync(out.fileno())
        temporary.replace(path);self.checkpoint_key=key

    def configure(self,spec,root):
        spec=copy.deepcopy(spec)
        if type(spec.get('game_id')) is not int or not 0<spec['game_id']<2**63 or not isinstance(spec.get('entry_id'),str) or not spec['entry_id']:
            raise ValueError('Coaching requires a concrete match entry')
        players=spec.get('players',[])
        if len(players)!=23:raise ValueError('Coaching requires the complete 23-player identity set')
        identities=[]
        identity_policy=spec.get('native_identity',{})
        if identity_policy and identity_policy.get('layout')!='serial32-padding32-card64':
            raise ValueError('Unknown native player identity layout')
        if self.execute and identity_policy and identity_policy.get('execution_verified') is not True:
            raise ValueError('Native CPU identity normalization is observation-only')
        for p in players:
            pair=(p.get('id'),p.get('serial'))
            if any(type(v) is not int or not 0<v<2**63 for v in pair):raise ValueError('Invalid coaching identity')
            serial=identity_policy.get('cpu_serial',pair[1])
            if type(serial) is not int or not -(1<<31)<=serial<(1<<32):raise ValueError('Invalid native player serial')
            identities.append((pair[0],serial&0xffffffff))
        if len(set(identities))!=23:raise ValueError('Duplicate coaching identity')
        fingerprint=signature(spec)
        with self.lock:
            if self.spec_hash==fingerprint:return False
            self.word('enabled',0);self.fence()
            seq=(struct.unpack('<I',self.read(self.layout['configuration_sequence'],4))[0]+2)&0xfffffffe
            if not seq:seq=2
            self.word('configuration_sequence',seq|1);self.fence()
            self.spec=spec;self.root=Path(root);self.spec_hash=fingerprint
            owner=re.match(r'^/data/(?:data|user/\d+)/([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/files(?:/|$)',self.root.as_posix())
            self.external_log=(Path('/storage/emulated/0/Android/data')/owner[1]/'files/personal-ai-coaching'
                               if spec.get('debug_external_status') is True and owner else None)
            self.epoch=secrets.randbits(63) or 1;self.sequence=0;self.last_snapshot=0;self.last_log=None;self.failed=None
            self.last_request=None;self.last_diagnostic=None
            self.checkpoint_key=None;self.recovering=False
            self.manager=Manager(spec)
            self.restore_policy()
            self.write(self.layout['expected'],b''.join(struct.pack('<QQ',*pair)for pair in identities))
            self.write(self.layout['epoch'],struct.pack('<Q',self.epoch))
            self.write(self.layout['game_id'],struct.pack('<Q',spec['game_id']))
            self.write(self.layout['snapshot'],bytes(4));self.write(self.layout['command'],bytes(440))
            self.word('diagnostic_enabled',int(spec.get('debug_external_status') is True))
            self.write(self.layout['diagnostic'],bytes(self.layout['diagnostic_bytes']))
            self.write(self.layout['ack_id'],bytes(8));self.word('ack_status',0);self.word('rejection_reason',0)
            self.word('heartbeat',1);self.word('auto_execute',int(self.execute));self.word('enabled',1)
            self.fence();self.word('configuration_sequence',seq);self.fence()
            self.log('configured',{'mode':'automatic' if self.execute else 'read_only',
                     'missing_proofs':[k for k in REQUIRED_PROOFS if self.proof.get(k) is not True],
                     'state_decoder_installed':callable(self.decoder),'style':spec.get('style'),
                     'coach_id':spec.get('coach_id'),'profile_id':spec.get('base_profile',{}).get('id'),
                     'players':[{'id':i,'serial':s}for i,s in identities]})
            self.wake.set();return True

    def deactivate(self,reason='entry closed'):
        with self.lock:
            if self.spec is None:return
            # This is invoked only after the accepted native exit boundary or
            # when configuring a disabled APK; no further policy decisions.
            self.word('auto_execute',0);self.word('enabled',0);self.fence()
            self.save_policy(closed=True,force=True)
            self.log('deactivated',{'reason':reason})
            self.spec=None;self.spec_hash=None;self.manager=None

    def native_log(self,snapshot):
        rows=[];plan=snapshot['raw_plan'];active=struct.unpack_from('<I',plan)[0]
        for p in snapshot['live']:
            p=dict(p);slot=p['lineup_slot']
            if slot and slot<11 and active in (0,1):
                base=active*0x3c+(slot-1)*6
                p['attack_grid']=[struct.unpack_from('<H',plan,0x124+base+2)[0],struct.unpack_from('<H',plan,0x19c+base+2)[0]]
                p['defence_grid']=[struct.unpack_from('<H',plan,0x124+base+4)[0],struct.unpack_from('<H',plan,0x19c+base+4)[0]]
            rows.append(p)
        state={k:v for k,v in snapshot.items()if k not in ('raw_plan','live')}
        state.update(live=rows,plan_active=active,plan_sha256=hashlib.sha256(plan).hexdigest(),
                     scope='configured complete roster; native match identifier binding not yet proven')
        state['native_duty_physical_indices']={
            'captain':struct.unpack_from('<I',plan,0xd24)[0],
            'set_piece_taker':list(struct.unpack_from('<6I',plan,0xd28)),
            'df_overlap_setplay':list(struct.unpack_from('<3I',plan,0xd40))}
        return state

    def scope_diagnostic(self):
        if self.spec.get('debug_external_status') is not True:return
        config=self.read(self.layout['configuration_sequence'],4)
        if int.from_bytes(config,'little')&1:return
        at=self.layout['diagnostic'];raw=self.read(at,self.layout['diagnostic_bytes'])
        if len(raw)!=392:return
        sequence,calls,team,count,reason,_=struct.unpack_from('<6I',raw)
        if sequence&1:return
        self.fence()
        if raw[:4]!=self.read(at,4) or config!=self.read(self.layout['configuration_sequence'],4):return
        actual=[{'id':i,'serial':s}for i,s in struct.iter_unpack('<QQ',raw[24:])if i or s]
        labels={0:'accepted' if calls else 'scope_not_observed',1:'missing_common',2:'human_control_detected',
                3:'missing_roster',4:'roster_count_mismatch',5:'physical_index_invalid',6:'missing_entry',
                7:'card_or_serial_mismatch',8:'duplicate_expected_identity',9:'configuration_changed'}
        key=(team,count,reason,tuple((p['id'],p['serial'])for p in actual),bool(calls))
        if key!=self.last_diagnostic:
            self.log('scope_diagnostic',{'native_scope_calls':calls,'team':team,'roster_count':count,
                     'reason':labels.get(reason,'unknown'),'raw_reason':reason,'actual_players':actual})
            self.last_diagnostic=key

    def step(self):
        with self.lock:
            if self.spec is None or self.failed:return None
            heartbeat=struct.unpack('<I',self.read(self.layout['heartbeat'],4))[0]
            self.word('heartbeat',(heartbeat+1)&0xffffffff or 1);self.fence()
            self.scope_diagnostic()
            snap=read_snapshot(self.read,self.layout,self.fence)
            if snap is None or snap['epoch']!=self.epoch or snap['game_id']!=self.spec['game_id']:
                return None
            if snap['sequence']==self.last_snapshot:return None
            snap['entry_id']=self.spec['entry_id']
            self.last_snapshot=snap['sequence']
            # Log immediately on score/stage/roster/state changes, otherwise
            # every30 GAME seconds, not every render frame or wall second.
            key=(snap['period'],snap['phase'],tuple(snap['score']),int(snap['clock_frames']//1800),
                 tuple((p['expected_index'],p['eligible'],p['native_flag_4202'],p['native_flag_4218'],
                        p['yellow_count'],p['direct_red'],p['injury_state'])for p in snap['live']))
            changed=key!=self.last_log
            if changed:
                self.log('native_snapshot',self.native_log(snap));self.last_log=key
            if not self.execute:
                if callable(self.decoder) and changed:
                    state=self.decoder(self.spec,snap)
                    self.log('state_decoded',{'accepted':state is not None,
                             'phase':state.get('phase') if state else None,
                             'minute':state.get('minute') if state else None,
                             'native_sequence':snap['sequence'],'automatic_execution_enabled':False})
                return snap
            decoded=self.decoder(self.spec,snap)
            if decoded is None:return snap
            if self.recovering:
                # Reconcile with the real native observation, then wait until
                # the following observation before permitting a new decision.
                if not self.manager.observe(decoded):return snap
                self.manager.record('restore_reconciled',sequence=decoded['sequence'],
                    on_field=list(decoded['on_field']))
                self.recovering=False;self.save_policy(decoded,force=True)
                self.log('policy_restored',{'native_sequence':snap['sequence'],
                         'pending_command_replayed':False})
                return snap
            proposal=self.manager.propose(decoded)
            decision=self.manager.state.get('last_decision')
            if decision is not None and decision!=getattr(self,'last_policy_decision',None):
                self.log('policy_decision',decision);self.last_policy_decision=copy.deepcopy(decision)
            cancellation=self.manager.cancellation()
            request=cancellation or proposal
            request_key=None if request is None else (request['kind'],request['id'],request.get('reason'))
            # Persist proposed/confirmed state before publishing a command.
            # If storage fails the worker falls back, rather than issuing an
            # action which cannot be reconciled after a technical recovery.
            self.save_policy(decoded,force=bool(request and request_key!=self.last_request))
            if request and request_key!=self.last_request:
                self.sequence=(self.sequence+2)&0xfffffffe or 2
                command=encode_command(self.layout,self.spec,snap,request,self.sequence,self.epoch)
                publish(self.write,self.layout['command'],command,self.fence)
                self.log('command_submitted',{'plan':request,'native_sequence':snap['sequence']})
                self.last_request=request_key
            return snap

    def start(self):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():return
            self.thread=threading.Thread(target=self.run,name='AI match bridge',daemon=True);self.thread.start()

    def run(self):
        while True:
            try:self.step()
            except Exception as error:
                with self.lock:
                    # Stop heartbeat so the native dead-worker fallback takes
                    # over; never continue issuing commands after an exception.
                    self.failed=str(error);self.log('worker_failed',{'error':str(error)})
                logging.getLogger(__name__).exception('AI match bridge failed; native fallback retained')
                return
            self.wake.wait(.1 if self.spec is not None else 5);self.wake.clear()


def register_channel(buffer,offset,layout,fence,proof=None,start=True):
    with _LOCK:
        for channel in _CHANNELS:
            if channel.view.obj is buffer and channel.offset==offset:return channel
        channel=Bridge(buffer,offset,layout,fence,proof,decode_match)
        _CHANNELS.append(channel)
        if _ACTIVE:channel.configure(*_ACTIVE)
        if start:channel.start()
        return channel


def activate(spec,root):
    global _ACTIVE
    with _LOCK:
        _ACTIVE=(copy.deepcopy(spec),root)
        for channel in _CHANNELS:channel.configure(spec,root)
        return {'channels':len(_CHANNELS),'execution_enabled':any(c.execute for c in _CHANNELS),
                'status':'observing' if _CHANNELS else 'waiting_for_native_channel'}


def deactivate(reason='entry closed'):
    global _ACTIVE
    with _LOCK:
        for channel in _CHANNELS:channel.deactivate(reason)
        _ACTIVE=None
