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
import time
from datetime import datetime,timezone
from pathlib import Path

from ai_match_channel import read_snapshot,encode_command,publish
from ai_match_manager import Manager,tournament_aptitude_exception
from ai_match_state import decode_normal,decode_match,rejection_reason

REQUIRED_PROOFS=('automatic_execution_verified','state_decoder_verified','entry_binding_verified',
                 'legal_windows_verified','emergency_reconciliation_verified',
                 'persistent_takeover_verified','whole_batch_window_verified','owned_release_verified')
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
        self.execution_capable=bool(callable(decoder) and all(self.proof.get(k) is True for k in REQUIRED_PROOFS))
        self.execute=self.execution_capable

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
        record={'utc':datetime.now(timezone.utc).isoformat(),'event':event,'entry_id':self.spec['entry_id'],'game_id':self.spec['game_id'],
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
        native_rules=spec.get('tournament_rules')
        relaxed_aptitude=tournament_aptitude_exception(spec)
        if 'tournament_fallback'in spec and not relaxed_aptitude:
            raise ValueError('Invalid tournament fallback policy')
        if relaxed_aptitude and (native_rules is None or 'tournament_relaxed_aptitude'not in self.layout):
            raise ValueError('Tournament fallback requires the scoped native tournament adapter')
        difficulty=spec.get('tournament_difficulty')
        native_levels=('VERYEASY','EASY','NORMAL','HARD','VERYHARD','HARDEST','LEGEND')
        if difficulty is not None:
            if difficulty not in native_levels:raise ValueError('Invalid tournament difficulty')
            if native_rules is None or 'difficulty_enabled'not in self.layout:
                raise ValueError('Native tournament difficulty adapter missing')
        if native_rules is not None:
            if not isinstance(native_rules,dict):raise ValueError('Invalid tournament rules')
            flags=('two_leg','first_leg','second_leg','extra_time','penalties','away_goals','away_goals_extra_time')
            if any(type(native_rules.get(k))is not bool for k in flags):raise ValueError('Invalid tournament rule flags')
            goals=native_rules.get('prior_goals')
            if not isinstance(goals,list)or len(goals)!=2 or any(type(v)is not int or not 0<=v<=99 for v in goals):raise ValueError('Invalid prior leg score')
            if 'rules_enabled'not in self.layout:raise ValueError('Native tournament rules adapter missing')
        with self.lock:
            if self.spec_hash==fingerprint and self.failed is None:return False
            self.word('enabled',0);self.fence()
            seq=(struct.unpack('<I',self.read(self.layout['configuration_sequence'],4))[0]+2)&0xfffffffe
            if not seq:seq=2
            self.word('configuration_sequence',seq|1);self.fence()
            self.spec=spec;self.root=Path(root);self.spec_hash=fingerprint
            self.execute=self.execution_capable and spec.get('auto_coaching',True) is not False
            owner=re.match(r'^/data/(?:data|user/\d+)/([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/files(?:/|$)',self.root.as_posix())
            self.external_log=(Path('/storage/emulated/0/Android/data')/owner[1]/'files/personal-ai-coaching'
                               if spec.get('debug_external_status') is True and owner else None)
            self.epoch=secrets.randbits(63) or 1;self.sequence=0;self.last_snapshot=0;self.last_log=None;self.failed=None
            self.last_valid_state_at=time.monotonic();self.state_is_healthy=False;self.last_ownership=None
            self.last_state_diagnostic=None;self.trusted_transition=False
            self.published_state=None;self.last_command_ack=None
            self.health_recovery_pending=('ownership_state'in self.layout and
                int.from_bytes(self.read(self.layout['ownership_state'],4),'little')!=0)
            if 'state_healthy'in self.layout:self.word('state_healthy',0)
            self.last_request=None;self.last_diagnostic=None
            self.attack_sequence=0
            self.last_attack_ack=None
            self.checkpoint_key=None;self.recovering=False
            self.manager=Manager(spec)
            self.restore_policy()
            diagnostic_events={'formation_target_lost','formation_cache_rebased_from_actual','formation_write_verified','formation_ack_awaiting_actual_shape',
                               'cancel_requested','cancel_retry','cancel_reconciled_from_native','batch_queued',
                               'waiting_legal_window','applied','partial','stale','rejected','ownership_released'}
            self.manager.event_sink=lambda event,payload:self.log('policy_'+event,payload)if event in diagnostic_events else None
            self.write(self.layout['expected'],b''.join(struct.pack('<QQ',*pair)for pair in identities))
            self.write(self.layout['epoch'],struct.pack('<Q',self.epoch))
            self.write(self.layout['game_id'],struct.pack('<Q',spec['game_id']))
            self.write(self.layout['snapshot'],bytes(4));self.write(self.layout['command'],bytes(440))
            # Bounded, deduplicated scope reasons belong to the private log.
            # An external mirror still requires its independent explicit opt-in.
            self.word('diagnostic_enabled',1)
            self.write(self.layout['diagnostic'],bytes(self.layout['diagnostic_bytes']))
            self.write(self.layout['ack_id'],bytes(8));self.word('ack_status',0);self.word('rejection_reason',0)
            if 'attack_command'in self.layout:
                self.write(self.layout['attack_command'],bytes(440))
                self.write(self.layout['attack_ack_id'],bytes(16))
            if 'rules_enabled'in self.layout:
                values=[0]*10
                if native_rules is not None:
                    values=[1,int(native_rules['two_leg']),int(native_rules['first_leg']),int(native_rules['second_leg']),
                            *native_rules['prior_goals'],int(native_rules['extra_time']),int(native_rules['penalties']),
                            int(native_rules['away_goals']),int(native_rules['away_goals_extra_time'])]
                self.write(self.layout['rules_enabled'],struct.pack('<10I',*values))
                self.word('rules_applied',0);self.write(self.layout['rules_epoch'],bytes(8))
            if 'difficulty_enabled'in self.layout:
                self.word('difficulty_enabled',int(difficulty is not None))
                self.word('difficulty_requested',native_levels.index(difficulty)if difficulty is not None else 0)
                for key in ('difficulty_applied','difficulty_before_offense','difficulty_before_defense',
                            'difficulty_after_offense','difficulty_after_defense'):
                    self.word(key,0)
                self.write(self.layout['difficulty_epoch'],bytes(8))
            if 'tournament_relaxed_aptitude'in self.layout:
                self.word('tournament_relaxed_aptitude',0x54584631 if relaxed_aptitude else 0)
            self.word('heartbeat',1);self.word('auto_execute',int(self.execute));self.word('enabled',1)
            self.fence();self.word('configuration_sequence',seq);self.fence()
            self.log('configured',{'mode':'automatic' if self.execute else 'read_only',
                     'missing_proofs':[k for k in REQUIRED_PROOFS if self.proof.get(k) is not True],
                     'state_decoder_installed':callable(self.decoder),'style':spec.get('style'),
                     'coach_id':spec.get('coach_id'),'profile_id':spec.get('base_profile',{}).get('id'),
                     'tournament_relaxed_aptitude':relaxed_aptitude,
                     'players':[{'id':i,'serial':s}for i,s in identities]})
            self.wake.set();return True

    def deactivate(self,reason='entry closed'):
        with self.lock:
            if self.spec is None:return
            # This is invoked only after the accepted native exit boundary or
            # when configuring a disabled APK; no further policy decisions.
            self.state_health(False,reason)
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
        config=self.read(self.layout['configuration_sequence'],4)
        if int.from_bytes(config,'little')&1:return
        at=self.layout['diagnostic'];raw=self.read(at,self.layout['diagnostic_bytes'])
        if len(raw)not in (392,408):return
        sequence,calls,team,count,reason,_=struct.unpack_from('<6I',raw)
        if sequence&1:return
        self.fence()
        if raw[:4]!=self.read(at,4) or config!=self.read(self.layout['configuration_sequence'],4):return
        actual=[{'id':i,'serial':s}for i,s in struct.iter_unpack('<QQ',raw[24:392])if i or s]
        labels={0:'accepted' if calls else 'scope_not_observed',1:'missing_common',2:'human_control_detected',
                3:'missing_roster',4:'roster_count_mismatch',5:'physical_index_invalid',6:'missing_entry',
                7:'card_or_serial_mismatch',8:'duplicate_expected_identity',9:'configuration_changed',10:'different_match_root'}
        key=(team,count,reason,tuple((p['id'],p['serial'])for p in actual),bool(calls))
        if key!=self.last_diagnostic:
            self.log('scope_diagnostic',{'native_scope_calls':calls,'team':team,'roster_count':count,
                     'reason':labels.get(reason,'unknown'),'raw_reason':reason,'actual_players':actual,
                     'callback_root':hex(struct.unpack_from('<Q',raw,392)[0])if len(raw)==408 else None,
                     'native_roster':hex(struct.unpack_from('<Q',raw,400)[0])if len(raw)==408 else None})
            self.last_diagnostic=key

    def state_health(self,healthy,reason,decoded=None):
        healthy=bool(healthy and self.execute)
        state=None
        if healthy and decoded is not None:
            state=(sum(1<<i for i in decoded['on_field']),decoded.get('period',0))
            if getattr(self,'state_is_healthy',False)and state!=getattr(self,'published_state',state):
                pending=self.manager.state.get('pending')if self.manager is not None else None
                progress=False
                if (pending and pending.get('kind')=='substitution' and
                    decoded.get('ack_id')==pending['id'] and decoded.get('ack_status')in ('accepted','applied')and
                    state[1]==self.published_state[1]):
                    initial=set(pending['initial_on_field']);current=set(decoded['on_field'])
                    incoming=set(pending['incoming']);target=(initial-set(pending['outgoing']))|incoming
                    progress=len(current)==pending['active_count']and current<=initial|incoming and initial&target<=current
                if not progress:
                    self.state_health(False,'native actors or period changed')
                    return False
        if healthy and getattr(self,'health_recovery_pending',False):
            if 'ownership_state'in self.layout and int.from_bytes(self.read(self.layout['ownership_state'],4),'little')!=0:
                return False
            self.health_recovery_pending=False
        if healthy and state is not None and 'state_field_mask'in self.layout:
            self.word('state_field_mask',state[0]);self.word('state_period',state[1])
            self.write(self.layout['state_epoch'],struct.pack('<Q',self.epoch));self.fence()
            self.published_state=state
        if 'state_healthy'in self.layout:
            self.word('state_healthy',int(healthy));self.fence()
        previous=getattr(self,'state_is_healthy',False)
        self.state_is_healthy=healthy
        if previous!=healthy:
            self.log('takeover_health',{'healthy':healthy,'reason':reason})
            if not healthy and self.manager is not None:
                self.health_recovery_pending=True
                self.manager.release_ownership(reason);self.last_request=None
        return healthy

    def ownership_diagnostic(self):
        if 'ownership_sequence'not in self.layout:return
        seq=self.read(self.layout['ownership_sequence'],4)
        if not int.from_bytes(seq,'little') or int.from_bytes(seq,'little')&1:return
        state,reason=struct.unpack('<II',self.read(self.layout['ownership_state'],8));self.fence()
        if seq!=self.read(self.layout['ownership_sequence'],4):return
        key=(state,reason)
        if key!=getattr(self,'last_ownership',None):
            labels={0:'native',1:'workshop',2:'draining_existing_native_queue',
                    3:'waiting_legal_window',4:'executing_owned_batch'}
            reasons={0:'healthy',1:'identity_or_entry_changed',2:'state_unreadable',
                     3:'worker_heartbeat_expired',4:'emergency_transition',5:'workshop_disabled',
                     18:'existing_native_queue',40:'period_changed',42:'trusted_transition_execution_suspended',
                     43:'unsupported_native_phase'}
            self.log('ownership_changed',{'owner':labels.get(state,'unknown'),
                      'reason':reasons.get(reason,str(reason))})
            if state==0 and reason in (4,40) and getattr(self,'state_is_healthy',False):
                self.state_health(False,reasons[reason])
            self.last_ownership=key

    def step(self):
        with self.lock:
            if self.spec is None or self.failed:return None
            heartbeat=struct.unpack('<I',self.read(self.layout['heartbeat'],4))[0]
            self.word('heartbeat',(heartbeat+1)&0xffffffff or 1);self.fence()
            self.ownership_diagnostic()
            self.scope_diagnostic()
            snap=read_snapshot(self.read,self.layout,self.fence)
            if snap is None or snap['epoch']!=self.epoch or snap['game_id']!=self.spec['game_id']:
                self.unavailable_state('snapshot_unreadable_or_torn'if snap is None else 'entry_identity_mismatch',snap)
                return None
            snap['entry_id']=self.spec['entry_id']
            if snap['sequence']==self.last_snapshot:
                # A coherent phase-3 observation deliberately suspends policy.
                # Its frozen game clock/sequence is not a dead worker. Native
                # still checks the full roster and a wall-clock heartbeat.
                if self.trusted_transition:
                    if self.state_is_healthy:
                        self.last_valid_state_at=time.monotonic()
                        return None
                    # Re-read a coherent suspended state after native release
                    # acknowledges recovery; it need not advance a game clock.
                else:
                    self.unavailable_state('snapshot_stalled',snap);return None
            if self.spec.get('tournament_difficulty')is not None and 'difficulty_enabled'in self.layout:
                epoch=struct.unpack('<Q',self.read(self.layout['difficulty_epoch'],8))[0]
                if epoch==self.epoch:
                    values={key:struct.unpack('<I',self.read(self.layout['difficulty_'+key],4))[0]
                            for key in ('applied','requested','before_offense','before_defense','after_offense','after_defense')}
                    if values!=getattr(self,'last_difficulty_diagnostic',None):
                        self.log('tournament_native_difficulty',values)
                        from action_trace import record_lifecycle
                        record_lifecycle('tournament_native_difficulty',dict(values,game_id=snap['game_id'],team=snap['team']))
                        self.last_difficulty_diagnostic=values
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
            if decoded is None:
                self.trusted_transition=False
                self.unavailable_state(rejection_reason(self.spec,snap),snap)
                return snap
            self.last_valid_state_at=time.monotonic()
            self.trusted_transition=bool(decoded.get('trusted_transition'))
            classification=('trusted_transition_execution_suspended'if self.trusted_transition else 'trusted_executable_state')
            self.state_diagnostic(classification,snap)
            if not self.state_health(True,'fresh coherent native state',decoded):return snap
            ack_key=(decoded.get('ack_id'),decoded.get('ack_status'),decoded.get('rejection_reason'))
            if ack_key[0] and ack_key!=self.last_command_ack:
                self.log('native_command_receipt',{'plan_id':ack_key[0],'native_status':ack_key[1],
                                                  'reason_code':ack_key[2]})
                self.last_command_ack=ack_key
            if self.recovering:
                if not self.manager.observe(decoded):return snap
                self.manager.record('restore_reconciled',sequence=decoded['sequence'],
                    on_field=list(decoded['on_field']))
                self.recovering=False;self.save_policy(decoded,force=True)
                self.log('policy_restored',{'native_sequence':snap['sequence'],
                         'pending_command_replayed':False})
                return snap
            if decoded.get('execution_allowed')is False:
                self.manager.observe(decoded)
                self.save_policy(decoded)
                return snap
            if 'attack_command'in self.layout:
                ack_id=self.read(self.layout['attack_ack_id'],8);self.fence()
                status,reason=struct.unpack('<II',self.read(self.layout['attack_ack_status'],8));self.fence()
                if ack_id==self.read(self.layout['attack_ack_id'],8):
                    from ai_match_channel import ACK_STATUS
                    decoded.update(attack_ack_id=int.from_bytes(ack_id,'little'),
                                   attack_ack_status=ACK_STATUS.get(status,'unknown'),attack_rejection_reason=reason)
                    key=(decoded['attack_ack_id'],status,reason)
                    if key[0] and key!=self.last_attack_ack:
                        self.log('attack_level_result',{'id':key[0],'status':decoded['attack_ack_status'],
                                 'reason':reason,'native_level':snap.get('current_attack_level')})
                        self.last_attack_ack=key
                attack=self.manager.propose_attack(decoded)
                if attack:
                    self.save_policy(decoded,force=True)
                    self.attack_sequence=(self.attack_sequence+2)&0xfffffffe or 2
                    raw=encode_command(self.layout,self.spec,snap,attack,self.attack_sequence,self.epoch)
                    publish(self.write,self.layout['attack_command'],raw,self.fence)
                    self.log('attack_level_submitted',{'plan':attack,'native_sequence':snap['sequence']})
            proposal=self.manager.propose(decoded)
            decision=self.manager.state.get('last_decision')
            if decision is not None and decision!=getattr(self,'last_policy_decision',None):
                self.log('policy_decision',decision);self.last_policy_decision=copy.deepcopy(decision)
            cancellation=self.manager.cancellation()
            request=cancellation or proposal
            request_key=None if request is None else (request['kind'],request['id'],request.get('reason'),request.get('generation'))
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

    def state_diagnostic(self,reason,snap):
        values={'reason':reason,'native_sequence':snap.get('sequence')if snap else None,
                'native_phase':snap.get('phase')if snap else None,'period':snap.get('period')if snap else None,
                'stop_reason':snap.get('stop_reason')if snap else None}
        key=(reason,values['native_phase'],values['period'],values['stop_reason'])
        if key!=self.last_state_diagnostic:
            self.log('state_classification',values);self.last_state_diagnostic=key

    def unavailable_state(self,reason,snap):
        if not self.execute:return
        if reason=='snapshot_stalled'and time.monotonic()-self.last_valid_state_at<=2:return
        self.state_diagnostic(reason,snap)
        if reason in ('entry_identity_mismatch','emergency_or_actor_transition')or time.monotonic()-self.last_valid_state_at>2:
            self.state_health(False,reason)

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
                    self.state_health(False,'worker failed')
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


def deactivate_for_match(game_id,reason='match finished'):
    """Close only this match, atomically with any replacement activation."""
    with _LOCK:
        if _ACTIVE is None or game_id is None or str(_ACTIVE[0].get('game_id'))!=str(game_id):return False
        deactivate(reason)
        return True
