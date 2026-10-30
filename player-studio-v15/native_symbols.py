"""Preview emblem lookup: prefer real/colour variants and installed patch roots."""
from pathlib import PurePosixPath
import shutil

def club_names(team):
    base=f'e_{int(team):06d}_r'
    return [base+s for s in ('_e_l','_l','_e','', '_e_s','_s','_w_l','_b_l','_w','_b')]

def resolve_club(symbols,team):
    if not team:return None
    real=next((symbols[name] for name in club_names(team) if name in symbols),None)
    if real:return real
    # The supplied mod installs licensed replacements under the stock fake
    # filenames. The suffix alone does not identify the actual artwork.
    base=f'e_{int(team):06d}_f'
    return next((symbols[name] for suffix in ('_l','','_s') if
                 (name:=base+suffix) in symbols and symbols[name].startswith('IDSPUCL27/')),None)


def converted_symbol(folder,reference):
    """CUE4Parse reports the mounted /Game path for IDSP replacement images.

    Android's decoder retains the requested mount. Materialize the exact
    selected symbol under that mount on PC too, so subsequent reads cache it.
    """
    from pathlib import Path
    ref=PurePosixPath(reference)
    if ref.is_absolute() or '..' in ref.parts:raise ValueError('队徽资源路径无效')
    target=Path(folder)/Path(reference).with_suffix('.png')
    if target.is_file() or not reference.startswith('IDSPUCL27/'):return target
    mounted=Path(folder)/Path('PesMobile/'+reference.split('/',1)[1]).with_suffix('.png')
    if mounted.is_file():
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(mounted,target)
    return target


def informative_symbol(path):
    """Do not present a flat placeholder texture as a real club crest."""
    from PIL import Image
    with Image.open(path) as im:
        rgba=im.convert('RGBA')
        return rgba.getbbox() is not None and any(hi-lo>4 for lo,hi in rgba.getextrema())

def merged_symbols(original,paths):
    result=dict(original);scores={key:0 for key in result}
    for path in paths:
        if '/ui/Data/Symbol/' not in path or not path.endswith('.uasset'):continue
        ref=path.removeprefix('../../../');name=PurePosixPath(ref).stem
        # V17's licensed replacement artwork is mounted under IDSPUCL27,
        # while the original index only scanned the PesMobile mount.
        priority=2 if ref.startswith('IDSPUCL27/') else 1
        if priority>=scores.get(name,-1):result[name]=ref;scores[name]=priority
    return result
