"""Restore the compressed public catalogue in a source ZIP checkout."""
from pathlib import Path
import gzip,hashlib,shutil

def main():
    resources=Path(__file__).resolve().parent/'resources'
    target=resources/'library.sqlite3';source=resources/'library.sqlite3.gz'
    expected=(resources/'library.sqlite3.sha256').read_text(encoding='ascii').strip()
    if target.is_file():
        if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
            raise ValueError('Existing database differs; preserve it and resolve manually.')
    else:
        temporary=target.with_suffix('.restoring')
        with gzip.open(source,'rb') as incoming,temporary.open('xb') as output:shutil.copyfileobj(incoming,output)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:
            temporary.unlink();raise ValueError('Public database checksum mismatch')
        temporary.replace(target)
    print('Public default catalogue ready.')

if __name__=='__main__':main()
