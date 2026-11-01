"""Editable level-one abilities; training and boosters have separate limits."""
import math

MINIMUM=40
MAXIMUM=103

def normalize(value,default=65):
    if isinstance(value,bool)or not isinstance(value,(int,float,str)):return default
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return default
    if not math.isfinite(value):return default
    return max(MINIMUM,min(MAXIMUM,int(value)))
