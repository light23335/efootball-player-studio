"""A 10,000-definition shared design library, separate from native APK IDs."""
import copy,json,threading,uuid
from custom_boosters import canonical

CAPACITY=10000
class BoosterLibrary:
    def __init__(self,root):self.path=root/'shared-boosters.json';self.lock=threading.RLock()
    def read(self):return json.loads(self.path.read_text(encoding='utf8')) if self.path.is_file() else {}
    def sync(self,project,previous=None):
        with self.lock:
            rows=self.read();changed=False
            before={b['uuid']:b for b in (previous or {}).get('custom_boosters',[])} if previous and previous.get('package_id')==project['package_id'] else {}
            used={r['id'] for r in rows.values()}
            for booster in project.get('custom_boosters',[]):
                uid=str(uuid.UUID(booster['uuid']))
                if uid not in rows:
                    if len(rows)>=CAPACITY:raise ValueError('共享增能库已达到 10000 项上限')
                    bid=booster['id'] if 1000<=booster['id']<11000 and booster['id'] not in used else next(i for i in range(1000,11000) if i not in used)
                    rows[uid]={**copy.deepcopy(booster),'id':bid};used.add(bid);changed=True
                elif uid in before and canonical(before[uid])!=canonical(booster):
                    rows[uid]={**copy.deepcopy(booster),'id':rows[uid]['id']};changed=True
            if changed:
                temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(self.path)
    def list(self,query='',offset=0):
        if type(offset) is not int or offset<0:raise ValueError('增能分页参数无效')
        with self.lock:
            values=list(self.read().values());query=str(query).casefold()[:120]
            rows=[r for r in values if query in (r['label']+' '+r['uuid']).casefold()]
            return {'rows':rows[offset:offset+50],'total':len(rows),'saved_total':len(values),'capacity':CAPACITY,'offset':offset}
