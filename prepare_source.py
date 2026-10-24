"""Restore the default database snapshot after cloning the source."""
from pathlib import Path
import gzip,shutil,hashlib
root=Path(__file__).resolve().parent
source=root/'player-studio-v15/resources/library.sqlite3.gz'
target=source.with_suffix('')
expected='abf58df873bc1085dea6e26dffe1769b3c94e74d8ebef1628bf128384fca1dc8'
if target.is_file():
    if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:raise RuntimeError('Existing database differs; keep it and resolve manually.')
else:
    temp=target.with_suffix('.restoring')
    with gzip.open(source,'rb') as src,temp.open('xb') as out:shutil.copyfileobj(src,out)
    if hashlib.sha256(temp.read_bytes()).hexdigest()!=expected:
        temp.unlink();raise RuntimeError('Database checksum mismatch')
    temp.replace(target)
print('Default public database ready.')
