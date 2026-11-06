"""Tournament person identity, matching V17's actual registration validator.

The native 0x6774f54(key, 1) keeps bits 0..22 and 52..63. Card/license
variant bits 23..51 do not make a second registrable footballer. This module
is intentionally separate from the existing AI-division identity policy.
"""
NATIVE_PERSON_MASK = 0xfff00000007fffff
REVISION = 'v17-native-registration-person-key-v1'


def native_person_key(card_id):
    return int(card_id) & NATIVE_PERSON_MASK


def person(card):
    # A stale private alias must never split a native duplicate into two people.
    return native_person_key(card['gameplayer_id']['id'])


def personal_identities(document):
    """Normalize compiled DIY aliases to the actual final native card keys.

An original-person binding is compiled into the card's native identity. A
legacy metadata claim that disagrees with that identity cannot change what
the native validator registers; all current and historical IDs use their
own actual key. Pending uncompiled projects are inspected separately.
    """
    result = {}
    for row in document.get('players', []):
        identity = row.get('identity') or {}
        owned = (row.get('owned') or {}).get('gameplayer_id') or {}
        for cid in (identity.get('card_id'), owned.get('id'), *identity.get('previous_card_ids', [])):
            if type(cid) is int and cid > 0:
                result[cid] = native_person_key(cid)
    return result
