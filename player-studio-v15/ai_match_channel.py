"""Versioned byte protocol for the game-thread CPU coaching adapter.

No native functions are called here. The compiled adapter publishes its layout;
every command uses that layout, a two-phase sequence and a content checksum.
This module alone never enables the native hooks or automatic execution.
"""
import math
import struct


ACK_STATUS = {1:'accepted',2:'applied',3:'rejected',4:'stale',5:'cancelled',6:'partial'}
KINDS = {'formation':1,'substitution':2,'cancel':3}


def checksum(raw):
    value = 2166136261
    for byte in raw[8:]:value = ((value ^ byte)*16777619) & 0xffffffff
    return value


def integer(value, bits=32):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError('Invalid coaching protocol integer')
    return value


def encode_command(layout, spec, snapshot, proposal, sequence, epoch):
    if not sequence or sequence & 1:raise ValueError('Command sequence must be positive and even')
    integer(sequence);integer(epoch,64)
    if proposal.get('game_id') != spec['game_id'] or proposal.get('entry_id') != spec.get('entry_id'):
        raise ValueError('Coaching proposal belongs to another entry')
    size = layout['command_bytes']
    if size != 440 or layout['placement_bytes'] != 28:
        raise ValueError('Unsupported native coaching command schema')
    raw = bytearray(size)
    def put(name,value,bits=32):
        struct.pack_into('<Q' if bits==64 else '<I',raw,layout['command.'+name],integer(value,bits))
    kind = proposal['kind']
    put('sequence',sequence);put('kind',KINDS[kind]);put('epoch',epoch,64)
    put('game_id',spec['game_id'],64);put('plan_id',proposal['id'],64)
    if kind != 'cancel':
        if snapshot.get('game_id') != spec['game_id'] or snapshot.get('entry_id') != spec.get('entry_id'):
            raise ValueError('Native snapshot belongs to another entry')
        put('based_on_snapshot',snapshot['sequence']);put('active_count',proposal['active_count'])
        for name,value in zip(('score_for','score_against'),proposal['score']):put(name,value)
        put('substitutions_left',snapshot['substitutions_left']);put('windows_left',snapshot['windows_left'])
        put('attack_level',proposal['attack_level'])
        clock = snapshot['clock_frames']
        if type(clock) not in (int,float) or not math.isfinite(clock) or clock<0:
            raise ValueError('Missing verified native clock')
        struct.pack_into('<f',raw,layout['command.issued_clock_frames'],clock)
        mapping = {int(slot):integer(index) for slot,index in proposal['mapping'].items()}
        count=proposal['active_count']
        if (not 7<=count<=11 or len(mapping)!=count or len(set(mapping.values()))!=count or
            any(type(slot)is not int or not 0<=slot<11 for slot in mapping) or 0 not in mapping):
            raise ValueError('Native placement must match the actual distinct active players')
        if proposal.get('policy_revision') in ('v17-situational-coach-v3','v17-situational-coach-v4','v17-situational-coach-v5-continuous-planning'):
            from ai_match_manager import resolve_profile
            profile=resolve_profile(spec,proposal['profile_id'],proposal['mode'])
        else:
            profile=next((p for p in spec['profiles']if p['id']==proposal['profile_id']),None)
            if profile is None:raise ValueError('Unknown coaching formation')
        def grid(row,role):
            if isinstance(row,dict):
                if row.get('role')!=role:raise ValueError('Formation coordinate role disagrees with placement')
                return row['position_x'],row['position_y']
            if isinstance(row,(tuple,list)) and len(row)==2:return row
            raise ValueError('Invalid formation coordinate record')
        put('placement_count',count)
        for at,(slot,index) in enumerate(sorted(mapping.items())):
            if index>=23:raise ValueError('Unknown native player identity')
            ax,ay = grid(profile['attack_coords'][slot],profile['attack'][slot])
            dx,dy = grid(profile['defence_coords'][slot],profile['defence'][slot])
            values = (index,profile['attack'][slot],profile['defence'][slot],ax,ay,dx,dy)
            if not 0<=values[1]<=12 or not 0<=values[2]<=12 or not 0<=ax<=48 or not 0<=dx<=48 or not 0<=ay<=104 or not 0<=dy<=104:
                raise ValueError('Invalid native role or formation coordinate')
            struct.pack_into('<7I',raw,layout['command.placement']+at*28,*(integer(v) for v in values))
        pairs = proposal.get('pairs',[])
        if len(pairs)>2 or {p[0] for p in pairs}!=set(proposal['incoming']) or {p[1] for p in pairs}!=set(proposal['outgoing']):
            raise ValueError('Missing verified legal substitution pairs')
        put('sub_count',len(pairs))
        for i,(inc,out) in enumerate(pairs):
            if not 0<=inc<23 or not 0<=out<23:raise ValueError('Unknown substitution identity')
            struct.pack_into('<I',raw,layout['command.incoming']+i*4,integer(inc))
            struct.pack_into('<I',raw,layout['command.outgoing']+i*4,integer(out))
        # Transport carries expected identities; only the game-thread adapter
        # resolves them to physical roster indices after native substitutions.
        duties=proposal.get('duties')
        for name,count in (('captain',1),('set_piece',6),('overlap',3)):
            values=([duties['captain']] if name=='captain' else duties['set_piece_taker'] if name=='set_piece'
                    else duties['df_overlap_setplay']) if duties else [255]*count
            if len(values)!=count or (duties and any(v not in mapping.values() for v in values)):
                raise ValueError('Duties must reference the proposed on-field identities')
            for i,value in enumerate(values):struct.pack_into('<I',raw,layout['command.'+name]+i*4,integer(value))
    put('checksum',checksum(raw))
    return bytes(raw)


def publish(write, offset, raw, fence):
    """Write callback accepts a byte offset and bytes, not an arbitrary pointer."""
    seq = struct.unpack_from('<I',raw)[0]
    if len(raw)!=440 or not seq or seq&1 or struct.unpack_from('<I',raw,4)[0]!=checksum(raw):
        raise ValueError('Incomplete coaching command')
    write(offset,struct.pack('<I',seq|1))
    fence()
    write(offset+4,raw[4:])
    fence()
    write(offset,raw[:4])
    fence()


def decode_match_clock(period, frames):
    """V17 period-local frames, not a wall clock or a cumulative minute.

    Original73462e8 returns45 for periods1/3 and15 for5/7. The native
    period transition6b1dff4..6b1e018 resets both the encoded counter and
    its accumulator. Keep the raw period clock for command freshness; use
    the scheduled offset only for tactical match-minute thresholds.
    Stoppage time may exceed the scheduled end and is never clamped away.
    Unknown/special periods are deliberately undecoded.
    """
    periods={1:('first_half',0,45,90),3:('second_half',45,45,90),
             5:('extra_first_half',90,15,120),7:('extra_second_half',105,15,120)}
    if type(period) is not int or period not in periods or type(frames) not in (int,float):return None
    if not math.isfinite(frames) or not 0<=frames<=65*3600:return None
    label,offset,length,end=periods[period]
    local=frames/3600
    return {'stage':label,'stage_minute':local,'minute':offset+local,
            'stage_end':offset+length,'period_end':end,'source':'v17_native_period_local_frames'}


def read_snapshot(read, layout, fence):
    """Seqlock read; return None instead of a torn or reconfigured snapshot."""
    at=layout['snapshot'];size=layout['snapshot_bytes']
    if size!=4880 or layout['live_player_bytes']!=36:
        raise ValueError('Unsupported native coaching snapshot schema')
    config=struct.unpack('<I',read(layout['configuration_sequence'],4))[0]
    if not config or config&1:return None
    fence()
    raw=read(at,size)
    sequence=struct.unpack_from('<I',raw,layout['snapshot.sequence'])[0]
    if not sequence or sequence&1:return None
    fence()
    if raw[:4]!=read(at,4) or config!=struct.unpack('<I',read(layout['configuration_sequence'],4))[0]:return None
    def get(name,fmt='I'):return struct.unpack_from('<'+fmt,raw,layout['snapshot.'+name])[0]
    if get('configuration_sequence')!=config or get('roster_count')!=23:return None
    fields=('expected_index','lineup_slot','physical_index','stamina','native_flag_4202',
            'native_flag_4218','eligible','attack_role','defence_role')
    live=[]
    for i in range(23):
        values=struct.unpack_from('<IIIiIIIII',raw,layout['snapshot.live']+i*36)
        live.append(dict(zip(fields,values)))
        live[-1]['stamina_source']='unknown' if values[3]<0 else 'native_live_ratio' if i<11 else 'native_entry_ratio'
        for field in ('yellow_count','direct_red','injury_state'):
            live[-1][field]=struct.unpack_from('<I',raw,layout['snapshot.'+field]+i*4)[0]
    if {p['expected_index'] for p in live}!=set(range(23)) or {p['lineup_slot'] for p in live}!=set(range(23)):
        return None
    if len({p['physical_index'] for p in live})!=23 or any(p['physical_index']>=40 for p in live):return None
    clock=get('clock_frames','f')
    if not math.isfinite(clock) or clock<0:return None
    result={name:get(name) for name in ('sequence','team','phase','period','stop_reason','substitutions_left',
                                       'windows_left','native_pending','native_event','post_event','current_attack_level')}
    result.update(epoch=get('epoch','Q'),game_id=get('game_id','Q'),clock_frames=clock,
                  score=[get('score_for','i'),get('score_against','i')],live=live,
                  raw_plan=raw[layout['snapshot.raw_plan']:layout['snapshot.raw_plan']+0xe6c])
    result['match_clock']=decode_match_clock(result['period'],clock)
    # Receipt publication sets ID last. Never join a new ID to old status.
    ack_id=read(layout['ack_id'],8)
    fence()
    status,reason=struct.unpack('<II',read(layout['ack_status'],8))
    fence()
    if ack_id==read(layout['ack_id'],8) and int.from_bytes(ack_id,'little'):
        result.update(ack_id=int.from_bytes(ack_id,'little'),ack_status=ACK_STATUS.get(status,'unknown'),rejection_reason=reason)
    return result
