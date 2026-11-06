"""Retain V22 music routing independently of the multi-draw scene policy."""
import base64,hashlib,json
from native_art import logical_package
from native_cpk import Cpk


def apply(raw,patch):
    digest=hashlib.sha256(raw).hexdigest()
    if digest==patch['after_sha256']:return raw,'reused'
    if len(raw)!=patch['bytes']or digest!=patch['before_sha256']:
        raise ValueError('抽卡音效资源与已核对的 V17／V22 版本不同，未覆盖未知内容')
    out=bytearray(raw);end=0
    for at,encoded in patch['edits']:
        data=base64.b64decode(encoded,validate=True)
        if type(at)is not int or at<end or at+len(data)>len(out):raise ValueError('抽卡音效补丁区间无效')
        out[at:at+len(data)]=data;end=at+len(data)
    if hashlib.sha256(out).hexdigest()!=patch['after_sha256']:raise ValueError('抽卡音效补丁读回校验失败')
    return bytes(out),'updated'


def compile_assets(library,resources,archive,replacements):
    if library.profile.get('game_version')!='V17':return [],{},[],{'enabled':False}
    config=json.loads((resources/'native-draw-v22-assets.json').read_text('utf8'))
    bp=config['blueprint'];raw,meta=library.face_assets().get(bp['path']);raw,bp_status=apply(raw,bp)
    packages=[(logical_package(bp['path']),raw,meta)]
    sound=config['sound'];member=sound['archive'];cpk=Cpk(replacements.get(member,archive.read(member)))
    value,status=apply(cpk.read(sound['member']),sound)
    output={}
    if status!='reused':
        # This ACB change is size-preserving. Keep all other stored CPK
        # entries (including CRILAYLA-compressed ones) and TOC bytes intact.
        row=cpk.toc.rows[cpk.files[sound['member']]]
        if row['FileSize']!=row['ExtractSize']or len(value)!=row['FileSize']:
            raise ValueError('抽卡音效库条目长度或压缩格式改变，未改写其他音效')
        at=cpk.base+row['FileOffset'];out=bytearray(cpk.raw);out[at:at+len(value)]=value
        output[member]=bytes(out)
    if output and Cpk(output[member]).read(sound['member'])!=value:raise ValueError('抽卡音效库写入校验失败')
    groups=[{'target':bp['path'].removeprefix('../../../'),'private_packages':[]}]
    from draw_v22 import REVISION
    return packages,output,groups,{'enabled':True,'revision':REVISION,
        'blueprint':bp_status,'sound':status,'blueprint_sha256':bp['after_sha256'],'sound_sha256':sound['after_sha256'],
        'in_game_playback_verified':False}
