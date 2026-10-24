"""Optional shared native person identity, with separate custom card ownership."""
from native_models import person_keys

BOUND_AGENT_MIN=4048


def normalize(identity,source=None):
    enabled=identity.get('bind_original_player',False)
    if type(enabled) is not bool:raise ValueError('原版球员身份绑定开关无效')
    raw=identity.get('original_player_id')
    if isinstance(raw,str):raw=raw.strip()
    if raw in (None,''):raw=(source or {}).get('id')
    if raw not in (None,''):
        if isinstance(raw,bool) or not str(raw).isascii() or not str(raw).isdigit() or not 0<int(raw)<2**63:
            raise ValueError('原游戏球员 ID 请填写有效的十进制编号')
        raw=str(int(raw))
    if enabled and not raw:raise ValueError('请先填写要绑定的原游戏球员 ID')
    identity['bind_original_player']=enabled;identity['original_player_id']=raw or None
    return int(raw) if enabled else None


def owned_person_aliases(identity):
    # Shared original person keys must never become owned replacement rows,
    # art routes, equipment entries or weekly-state records of a custom card.
    if identity.get('bound_original_player_id'):return []
    return list(map(int,person_keys(identity['person_id'])))
