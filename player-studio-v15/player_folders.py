"""Local player categories keyed by permanent project UUIDs; no file moves."""
from pathlib import Path
import copy,json,os,uuid


def identity(value):
    try:
        if not isinstance(value,str) or str(uuid.UUID(value))!=value:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ValueError('球员或文件夹的永久身份无效') from None
    return value


def name(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=60 or any(ord(c)<32 for c in value):
        raise ValueError('文件夹名称请填写 1–60 个字符，不可包含换行')
    return value.strip()


class PlayerFolders:
    def __init__(self,store):
        self.store=store;self.path=store.root/'player-folders.json';self.lock=store.lock

    def read(self):
        if not self.path.exists():return {'version':1,'folders':[],'members':{}}
        try:
            if self.path.stat().st_size>8*1024*1024:raise ValueError('文件过大')
            data=json.loads(self.path.read_text('utf8'))
            if not isinstance(data,dict):raise ValueError('格式不正确')
            if data.get('version')!=1 or not isinstance(data.get('folders'),list) or not isinstance(data.get('members'),dict):raise ValueError('格式不正确')
            if len(data['folders'])>10000 or len(data['members'])>10000:raise ValueError('记录数量异常')
            ids=set();names=set()
            for row in data['folders']:
                ident=identity(row['id']);label=name(row['name']).casefold()
                if ident in ids or label in names:raise ValueError('存在重复文件夹')
                ids.add(ident);names.add(label)
            for player,folder in data['members'].items():
                identity(player)
                if folder not in ids:raise ValueError('分类引用不存在的文件夹')
            return data
        except (ValueError,KeyError,TypeError,OSError) as error:
            raise ValueError('球员文件夹资料无法读取：'+str(error)+'。原文件已保留。') from error

    def _write(self,data):
        previous=self.path.read_bytes() if self.path.exists() else None
        if previous is not None:
            backup=self.store.root/'backups'/('player-folders-'+uuid.uuid4().hex+'.json')
            backup.write_bytes(previous)
        temporary=self.path.with_name('.player-folders-'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('w',encoding='utf8') as out:
                json.dump(data,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
            os.replace(temporary,self.path)
        finally:
            if temporary.exists():temporary.unlink()

    def listing(self):
        with self.lock:
            data=self.read();existing={p.stem for p in (self.store.root/'players').glob('*.json')}
            counts={r['id']:0 for r in data['folders']}
            for player,folder in data['members'].items():
                if player in existing:counts[folder]+=1
            rows=[dict(r,count=counts[r['id']]) for r in data['folders']]
            return {'rows':rows,'all_count':len(existing),'unfiled_count':len(existing)-sum(counts.values())}

    def _players(self,values,empty=False):
        if not isinstance(values,list) or len(values)>10000 or not empty and not values:raise ValueError('请勾选要添加的已有球员')
        values=list(dict.fromkeys(identity(v) for v in values))
        for ident in values:
            if not self.store._player_path(ident).is_file():raise ValueError('所选球员已不存在：'+ident+'，未修改任何分类')
        return values

    @staticmethod
    def _folder(data,ident):
        ident=identity(ident)
        row=next((r for r in data['folders'] if r['id']==ident),None)
        if row is None:raise ValueError('文件夹已不存在，请刷新列表')
        return row

    def create(self,label,players=None):
        with self.lock:
            data=self.read();label=name(label);players=self._players([] if players is None else players,empty=True)
            if any(r['name'].casefold()==label.casefold() for r in data['folders']):raise ValueError('已有同名文件夹，请换一个名称')
            if len(data['folders'])>=10000:raise ValueError('文件夹数量已达 10000 个')
            row={'id':str(uuid.uuid4()),'name':label};data['folders'].append(row)
            for player in players:data['members'][player]=row['id']
            self._write(data)
            return {'folder':row,'added':len(players),**self.listing()}

    def add(self,ident,players):
        with self.lock:
            data=self.read();row=self._folder(data,ident);players=self._players(players)
            added=sum(data['members'].get(p)!=ident for p in players)
            for player in players:data['members'][player]=ident
            self._write(data)
            return {'folder':row,'added':added,**self.listing()}

    def remove(self,ident,players):
        with self.lock:
            data=self.read();row=self._folder(data,ident);players=self._players(players)
            removed=0
            for player in players:
                if data['members'].get(player)==ident:data['members'].pop(player);removed+=1
            self._write(data)
            return {'folder':row,'removed':removed,**self.listing()}

    def rename(self,ident,label):
        with self.lock:
            data=self.read();row=self._folder(data,ident);label=name(label)
            if any(r['id']!=ident and r['name'].casefold()==label.casefold() for r in data['folders']):raise ValueError('已有同名文件夹')
            row['name']=label;self._write(data)
            return {'folder':row,**self.listing()}

    def delete(self,ident,confirmed=False):
        if confirmed is not True:raise ValueError('请先确认删除文件夹；球员仍会保留')
        with self.lock:
            data=self.read();row=self._folder(data,ident)
            data['folders']=[r for r in data['folders'] if r['id']!=ident]
            data['members']={p:f for p,f in data['members'].items() if f!=ident};self._write(data)
            return {'deleted':True,'folder':row,**self.listing()}

    def forget(self,player):
        with self.lock:
            data=self.read()
            if player in data['members']:data['members'].pop(player);self._write(data)
