"""Resolve existing face meshes, including versioned legend/epic resources."""
import re


def person_keys(player_id):
    """Keep exact identities first, then remove native card/person flags.

    e.g. BT Mane 89137029898200 stores 0x0500dfd8 in its low 28 bits;
    the real face family is 57304 (0xdfd8), not 83943384.
    """
    value=int(player_id)
    return list(dict.fromkeys(str(v) for v in (value,value&0xfffffff,value&0xffffff,value&0x7fffff,value&0x3fffff) if v))


def resolve_face(rows, player_id):
    faces=[r for r in rows if re.fullmatch(r'SK_\d+(?:(?:ep|lg)\d+v\d+)?_Face',r['name'])]
    agent=(int(player_id)>>28)&4095
    exact=next((r for r in faces if r['name']==f'SK_{player_id}_Face'),None)
    versioned=[r for r in faces if re.search(rf'(?:ep|lg)\d+v{agent:04d}_Face$',r['name'])]
    generic=next((r for r in faces if re.fullmatch(r'SK_\d+_Face',r['name'])),None)
    if exact:return exact,{'method':'card-id','exact':True}
    if versioned:return versioned[0],{'method':'native-variant','exact':True,'variant':versioned[0]['name']}
    if generic:return generic,{'method':'native-person','exact':True}
    if len(faces)==1:return faces[0],{'method':'only-native-face','exact':True,'variant':faces[0]['name']}
    if faces:
        family='lg' if (int(player_id)>>40)&255==0x10 else 'ep'
        chosen=next((r for r in faces if family in r['name']),faces[0])
        return chosen,{'method':'same-player-variant','exact':False,'variant':chosen['name'],
                       'message':'当前卡号没有唯一匹配的脸模变体，已预览同一球员的原版脸模，可切换下列版本。'}
    return None,{'method':'unavailable','exact':False,'message':'当前两个 APK 未索引到该球员的原版脸部网格。'}
