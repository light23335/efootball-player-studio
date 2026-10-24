"""Read shirt numbers from the native assignment table, not the card template."""
from native_cpk import unwrap
from native_models import person_keys

TABLE='common/etc/pesdb/PlayerAssignment.bin'


def assignments(sources):
    result={}
    for source in sources:
        if TABLE not in source.files:continue
        raw=unwrap(source.read(TABLE))
        if len(raw)%24:raise ValueError('原生球员号码表长度改变')
        for at in range(0,len(raw),24):
            row=raw[at:at+24]
            ident=int.from_bytes(row[:8],'little')
            result[ident]={'player_id':int.from_bytes(row[8:16],'little'),
                           'team_id':int.from_bytes(row[16:20],'little'),
                           # V17 getter 0x8251910: (row.u16[20] & 1023) + 1.
                           'number':(int.from_bytes(row[20:22],'little')&1023)+1}
    by_player={}
    for row in result.values():by_player.setdefault(row['player_id'],[]).append(row)
    return by_player


def restore(payload,ident,team_id,by_player):
    number=payload.get('uniform_number')
    if type(number) is int and 1<=number<=999:
        payload['_studio_number_source']='原包球员资料';return
    choices=[]
    for key in person_keys(ident):
        for row in by_player.get(int(key),[]):
            if 1<=row['number']<=999:choices.append(row)
    selected=next((row for row in choices if row['team_id']==team_id),None)
    if selected is None:selected=next((row for row in choices if row['team_id']>=100),None)
    if selected is None:selected=next(iter(choices),None)
    payload['uniform_number']=selected['number'] if selected else None
    payload['_studio_number_source']='原生阵容表 · 球队 '+str(selected['team_id']) if selected else '原包未提供号码'
