"""Exact personal front overrides, independent of old series filename rules."""

def front_overrides(card,asset_key):
    # None retains the native decoration; '' deliberately clears that layer.
    # F07 must always use the full portrait, never the mini '_' / '_m' image.
    front=[None]*10
    front[6]=str(asset_key)+'f'
    front[5]=front[8]=''  # F06 decoration and baked F09 date are suppressed.
    if card.get('preset_id'):front[3]=''  # F04 is already in the full portrait.
    return front
