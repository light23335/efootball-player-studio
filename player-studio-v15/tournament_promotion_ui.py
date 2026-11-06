"""Persisted tournament progression -> original native promotion actor.

The worker only reads/writes the bounded shared channel. Native creation,
button confirmation and actor lifetime checks run on the game's UI thread.
"""
from contextlib import closing
import copy,json,logging,secrets,sqlite3,threading,time
from pathlib import Path
import tournament_promotion as promotion

LOG=logging.getLogger(__name__)
_SERVICE=_CHANNEL=_WORKER=None
_LOCK=threading.RLock()
_PROCESS=secrets.token_hex(16)


def _database(root):
    path=(Path(root)/'outputs/efootball/local-club.sqlite3').resolve()
    return path if path.is_file()else None


def offer(root,definitions,event,generation,process=_PROCESS):
    """Commit the delivery token BEFORE publishing any native command."""
    from tournament_runtime import PREFIX,LOCK
    definition=next((t for t in definitions if t.get('event_id')==event and t.get('enabled',True)),None)
    path=_database(root)
    if definition is None or path is None:return None
    session=process+':menu:'+str(generation)
    with LOCK,closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=2))as conn,conn:
        conn.execute('begin immediate');key=PREFIX+definition['uuid']
        row=conn.execute('select value from meta where key=?',(key,)).fetchone()
        if row is None:return None
        current=json.loads(row[0]);pending=promotion.pending(current)
        if pending is None or pending['animation']!='PROMOTED':return None
        result=promotion.begin(current,session)
        if result is None:
            delivery=current[promotion.KEY].get('delivery')
            if not delivery or delivery.get('session_id')!=session or delivery.get('event_id')!=pending['id']:return None
            result={'event':pending,'delivery':delivery,'view':promotion.view(current,pending)}
        conn.execute('update meta set value=? where key=?',(json.dumps(current,ensure_ascii=False,separators=(',',':')),key))
        return {'uuid':definition['uuid'],'run_id':current['run_id'],'event':event,'generation':generation,
                'event_id':pending['id'],'token':result['delivery']['token'],'view':copy.deepcopy(result['view'])}


def _receipt(root,ticket,confirmed):
    """Merge the receipt into the latest state; never write an old UI copy."""
    from tournament_runtime import PREFIX,LOCK
    path=_database(root)
    if path is None:return False
    with LOCK,closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=2))as conn,conn:
        conn.execute('begin immediate');key=PREFIX+ticket['uuid']
        row=conn.execute('select value from meta where key=?',(key,)).fetchone()
        if row is None:return False
        current=json.loads(row[0])
        if current.get('run_id')!=ticket['run_id']:return False
        fn=promotion.confirm if confirmed else promotion.release
        changed=fn(current,ticket['event_id'],ticket['token'])
        if changed:conn.execute('update meta set value=? where key=?',(json.dumps(current,ensure_ascii=False,separators=(',',':')),key))
        return changed


def _receipt_state(root,ticket):
    """Separate transient storage absence from a superseded event delivery."""
    from tournament_runtime import PREFIX,LOCK
    path=_database(root)
    if path is None:return 'unavailable'
    with LOCK,closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2))as conn:
        row=conn.execute('select value from meta where key=?',(PREFIX+ticket['uuid'],)).fetchone()
    if row is None:return 'stale'
    current=json.loads(row[0])
    if current.get('run_id')!=ticket['run_id']:return 'stale'
    journal=current.get(promotion.KEY,{})
    event=next((e for e in journal.get('events',[])if e['id']==ticket['event_id']),None)
    if event is None:return 'stale'
    if event.get('status')=='confirmed':return 'current'if event.get('confirmed_token')==ticket['token']else 'stale'
    delivery=journal.get('delivery')
    return 'current'if delivery and delivery.get('event_id')==ticket['event_id']and delivery.get('token')==ticket['token']else 'stale'


class Presenter:
    def __init__(self,service,channel,clock=time.monotonic,process=_PROCESS):
        self.service=service;self.channel=channel;self.clock=clock;self.process=process
        self.ticket=None;self.confirmed=False;self.signal=None;self.signal_at=0;self.retry_at=0;self.blocked=None

    def persist_receipt(self,confirmed):
        ticket=self.ticket
        if _receipt(self.service.root,ticket,confirmed)is True:return True
        reason=_receipt_state(self.service.root,ticket)
        if reason=='stale':
            # A later run/menu owns the DB now. Retire only this old transport
            # token; never confirm, release or overwrite the new journal.
            self.channel.promotion_clear(ticket);self.ticket=None;self.confirmed=False
            self.retry_at=self.clock()+.2
            LOG.info('Tournament native promotion stale delivery handed off: run=%s event=%s',ticket['run_id'],ticket['event_id'])
        # A false/unknown receipt with the same delivery, including a missing
        # database, is retryable. Do not consume it locally or clear native ACK.
        return False

    def tick(self):
        state=self.channel.promotion_status()
        if self.ticket:
            ticket=self.ticket
            if state and state['token']==ticket['token'][:32]and state['generation']==ticket['generation']:
                if state['status']in(2,5):
                    if not self.confirmed:
                        if not self.persist_receipt(True):return False
                        self.confirmed=True
                        LOG.info('Tournament native promotion confirmed: run=%s event=%s',ticket['run_id'],ticket['event_id'])
                    if state['status']==5:
                        self.channel.promotion_clear(ticket);self.ticket=None
                    return True
                if state['status']in(3,4):
                    if not self.persist_receipt(False):return False
                    self.channel.promotion_clear(ticket);self.ticket=None;self.retry_at=self.clock()+3
                    if state['status']==4:self.blocked=ticket['generation']
                    LOG.info('Tournament native promotion retained: native_status=%s reason=%s',state['status'],state['reason'])
            return False
        if state and state['status']in(1,2)or self.clock()<self.retry_at:return False
        menu=self.channel.promotion_menu()
        if not menu or not menu['event']or not menu['generation']or menu['generation']==self.blocked:return False
        signal=(menu['event'],menu['generation'],menu['tick'])
        if signal!=self.signal:self.signal=signal;self.signal_at=self.clock()
        if self.clock()-self.signal_at>2:return False
        import native_tournament_schedule_ui as schedule
        if schedule._HOST is not None and(schedule._HOST.pending or schedule._HOST.shown):return False
        ticket=offer(self.service.root,self.service.definitions(),menu['event'],menu['generation'],self.process)
        if ticket is None:return False
        self.ticket=ticket;self.confirmed=False
        self.channel.promotion_request(ticket)
        LOG.info('Tournament native promotion submitted: run=%s event=%s menu=%s',ticket['run_id'],ticket['event_id'],ticket['generation'])
        return True


def configure(service):
    global _SERVICE
    with _LOCK:_SERVICE=service
    _start()


def channel_ready(channel):
    global _CHANNEL
    with _LOCK:_CHANNEL=channel
    _start()


def _start():
    global _WORKER
    with _LOCK:
        if _SERVICE is None or _CHANNEL is None or _WORKER is not None and _WORKER.is_alive():return
        _CHANNEL.promotion_enable();presenter=Presenter(_SERVICE,_CHANNEL)
        def work():
            while True:
                try:presenter.tick()
                except Exception:LOG.exception('Tournament native promotion retained; retrying')
                time.sleep(.1)
        _WORKER=threading.Thread(target=work,name='studio-tournament-promotion',daemon=True);_WORKER.start()
