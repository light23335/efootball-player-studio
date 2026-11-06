"""Keep the original offline eFootball League open for a saved 2,500-day window.

Only availability timestamps are projected into native responses. Division,
points, matches, receipts, phase identity and rewards remain authoritative.
There are no database writes or game UI calls on import.
"""
import functools
import json
import logging
import struct
import threading
import time

REVISION='studio-original-league-availability-v1'
RUNTIME_REVISION='studio-original-league-native-cache-v2'
KEY='studio_original_league_availability_v1'
DAYS=2500
DURATION=DAYS*24*60*60
LOG=logging.getLogger(__name__)
NATIVE_OFFSET=40
NATIVE_MAGIC=20261105
_CHANNEL=None
_WINDOW=None
_LOCK=threading.RLock()


def _publish_native(channel,value):
    """Only the unused 24-byte home-channel header tail is ours."""
    at=channel.offset+NATIVE_OFFSET
    seq=(struct.unpack_from('<I',channel.buffer,at)[0]+2)&0xfffffffe or 2
    struct.pack_into('<I',channel.buffer,at,seq|1);channel.fence()
    struct.pack_into('<IQQ',channel.buffer,at+4,NATIVE_MAGIC,value['start'],value['end'])
    channel.fence();struct.pack_into('<I',channel.buffer,at,seq);channel.fence()


def publish_native(value):
    global _WINDOW
    with _LOCK:
        _WINDOW=dict(value)
        if _CHANNEL:_publish_native(_CHANNEL,_WINDOW)


def channel_ready(channel):
    global _CHANNEL
    with _LOCK:
        _CHANNEL=channel
        if _WINDOW:_publish_native(channel,_WINDOW)


def window(conn,now):
    """Reuse one persisted deadline; renew availability without a season reset."""
    if type(now)not in (int,float)or not 0<=now<2**53:raise ValueError('Invalid league availability clock')
    now=int(now)
    row=conn.execute('select value from meta where key=?',(KEY,)).fetchone()
    try:old=json.loads(row[0])if row else None
    except(ValueError,TypeError):old=None
    valid=(isinstance(old,dict)and old.get('revision')==REVISION and old.get('days')==DAYS and
           type(old.get('start'))is int and type(old.get('end'))is int and
           old['end']-old['start']==DURATION)
    if valid and old['start']<=now<old['end']:return old
    value={'revision':REVISION,'days':DAYS,'start':now,'end':now+DURATION}
    # Do not commit a transaction owned by a gateway caller. A normal response
    # is projected after settlement has committed; startup may own its own tx.
    foreign=conn.in_transaction
    def write():
        conn.execute('insert into meta values(?,?) on conflict(key)do update set value=excluded.value',
                     (KEY,json.dumps(value,separators=(',',':'))))
    if foreign:write()
    else:
        with conn:write()
    LOG.info('Original league availability opened: start=%s end=%s days=%s',value['start'],value['end'],DAYS)
    return value


def targets(response):
    """Only the original native League entry, detail and result contracts."""
    if not isinstance(response,dict)or response.get('result')!='NOERR':return []
    rows=[]
    info=response.get('league_info')
    if isinstance(info,dict):
        if {'league_phase_start_time','league_phase_end_time'}<=info.keys():
            rows.append((info,'league_phase_start_time','league_phase_end_time'))
        if {'phase_id','phase_start_time','phase_end_time','current_division'}<=info.keys():
            rows.append((info,'phase_start_time','phase_end_time'))
    result=response.get('game_end_result')
    extra=result.get('extra_match_result')if isinstance(result,dict)else None
    league=extra.get('league_match_result')if isinstance(extra,dict)else None
    info=league.get('league_info')if isinstance(league,dict)else None
    if isinstance(info,dict)and {'phase_id','phase_start_time','phase_end_time','current_division'}<=info.keys():
        rows.append((info,'phase_start_time','phase_end_time'))
    return rows


def project(response,value):
    for row,start,end in targets(response):
        # Extending a phase must not move its opening time forward. The
        # native menu uses a separately calibrated clock, which may lag the
        # Python reply by several seconds. Keep a legitimate earlier opening.
        old=row.get(start)
        row[start]=min(old,value['start'])if type(old)is int and old>0 else value['start']
        row[end]=value['end']
    return response


def install(logic,clock=None):
    """Wrap the final gateway reply so cached/ported templates agree too."""
    if logic is None:return False
    cls=type(logic);previous=cls.handle
    if getattr(previous,'_studio_league_availability',False):return False
    clock=clock or time.time;lock=threading.RLock()
    # Old native menu caches can be consumed before another creative-info
    # request. Publish the saved deadline during startup as well as replies.
    publish_native(window(logic.conn,clock()))
    seen=set()
    @functools.wraps(previous)
    def handle(self,command,request):
        response=previous(self,command,request)
        if targets(response):
            with lock:
                value=window(self.conn,clock());project(response,value);publish_native(value)
                if command not in seen:
                    seen.add(command)
                    print('STUDIO_ORIGINAL_LEAGUE',RUNTIME_REVISION,command,
                          'deadline',value['end'],'native_cache_published',bool(_CHANNEL),
                          'native_cache_syncs',struct.unpack_from('<I',_CHANNEL.buffer,_CHANNEL.offset+12)[0]if _CHANNEL else 0)
        return response
    handle._studio_league_availability=True
    cls.handle=handle
    return True
