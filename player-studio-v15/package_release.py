"""Archive a verified, explicitly prepared public portable directory."""
from pathlib import Path
import argparse,hashlib,json,os,re,zipfile
ROOT=Path(__file__).resolve().parent
VERSION=re.search(r'APP_VERSION = "([^"]+)"',(ROOT/'app.py').read_text(encoding='utf8'))[1]
GAME=json.loads((ROOT/'resources/native-resource-profile.json').read_text(encoding='utf8')).get('game_version','V17')
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(8*1024*1024),b''):h.update(data)
    return h.hexdigest()
def archive(source,output,portable=False):
    temp=output.with_suffix('.building.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for base,dirs,names in os.walk(source):
            dirs[:]=[d for d in dirs if d not in ('data','__pycache__','.git','.codex','.agents','.venv') and not Path(base,d).is_symlink() and not Path(base,d).is_junction()]
            for name in sorted(names):
                p=Path(base,name);rel=p.relative_to(source)
                if p.is_symlink() or p.suffix in ('.pyc','.pyo','.log','.tmp'):continue
                if p.suffix.lower() in ('.apk','.pem','.efplayer','.efsave','.efproject'):raise ValueError('发现个人内容或游戏包，停止发布：'+str(rel))
                if portable and rel.parts[0] not in ('球员工坊.exe','tools','library','先读我.txt','使用说明.md','第三方说明.txt','测试说明.json','SHA256.txt'):raise ValueError('分享目录有未授权内容：'+str(rel))
                if portable and rel.parts[0]=='library' and not ('containers' in rel.parts or rel.name=='ready.json'):raise ValueError('分享目录存在非原始缓存：'+str(rel))
                z.write(p,source.name+'/'+rel.as_posix())
    with zipfile.ZipFile(temp) as z:
        if z.testzip() is not None:raise ValueError('分享包 CRC 校验失败')
        if any('/data/' in n or n.endswith(('.pem','.efplayer','.efsave','.efproject','.apk')) for n in z.namelist()):raise ValueError('归档包含个人数据')
    temp.replace(output)
    return {'path':str(output),'bytes':output.stat().st_size,'sha256':sha(output)}
def main():
    p=argparse.ArgumentParser();p.add_argument('--dist-dir',required=True);args=p.parse_args();dist=Path(args.dist_dir).resolve()
    report=json.loads((dist/'测试说明.json').read_text(encoding='utf8'))
    if report['version']!=VERSION or report['exe_sha256']!=sha(dist/'球员工坊.exe'):raise ValueError('发布 EXE 与验收版本不一致')
    results=[archive(dist,ROOT.parent/f'球员工坊-{GAME}-v{VERSION}-免安装分享版.zip',True),archive(ROOT,ROOT.parent/f'球员工坊-{GAME}-v{VERSION}-源码.zip')]
    print(json.dumps({'game':GAME,'version':VERSION,'archives':results},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
