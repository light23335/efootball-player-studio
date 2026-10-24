"""Celebration in V15's 400-byte player rows and 147-item wire parameters.

The field at bit 352 (9 bits) agrees with all 269 nonzero complete card
payloads in the supplied V15 APK. Older catalogues left parameter 59 at zero;
read their preserved native row instead of treating that placeholder as data.
"""
FIELD={'bit':352,'width':9}
PARAMETER=59
MAXIMUM=(1<<FIELD['width'])-1


def validate(value):
    if type(value) is not int or not 0<=value<=MAXIMUM:
        raise ValueError('庆祝动作编号须为 0–511 的整数，留空沿用源球员')
    return value


def from_record(row):
    if len(row)!=400:raise ValueError('庆祝动作的原生球员记录长度不兼容')
    return (int.from_bytes(row,'little')>>FIELD['bit'])&MAXIMUM


def from_payload(payload):
    raw=payload.get('_studio_client_record')
    if raw is not None:
        try:row=bytes.fromhex(raw)
        except (TypeError,ValueError) as exc:raise ValueError('庆祝动作的原生球员记录无效') from exc
        return from_record(row)
    params=payload.get('parameters') or []
    if len(params)>PARAMETER:return validate(params[PARAMETER])
    return None


def restore_payload(payload):
    """Hydrate a newly read dictionary; never rewrite the saved catalogue."""
    value=from_payload(payload)
    if value is None:return payload
    for key in ('parameters','_careerplan_base_parameters'):
        if len(payload.get(key) or [])>PARAMETER:
            values=list(payload[key]);values[PARAMETER]=value;payload[key]=values
    return payload


def project_value(project,template,source_record=None):
    if project.get('celebration') is not None:return validate(project['celebration'])
    value=from_payload((project.get('source_player') or {}).get('original_payload') or {})
    if value is None and source_record is not None:value=from_record(source_record)
    if value is None:value=from_payload(template)
    return value if value is not None else 0
