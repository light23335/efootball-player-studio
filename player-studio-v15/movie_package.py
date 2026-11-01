"""Merge verified movie maps; cache the complete inner archive by content."""
import hashlib
from pathlib import Path
import zipfile
from export_payload import FilePayload,ZipPayload,identity

MEMBER='assets/pc0000_mobile_and.pak'
REVISION='movie-package-direct-cache-v2'


def merge(archive,existing,private,native,work,cache=None):
    from private_card_motion import read_movie_pak,write_movie_pak
    from apk_format import replace_entries
    work=Path(work)
    # Hash the actual chosen bytes, not an APK filename/mtime or an untrusted
    # release label. A coach replacement, if present, is the merge baseline.
    if existing is not None and not isinstance(existing,FilePayload):
        raise TypeError('Movie archive baseline must be a file payload')
    baseline=existing or FilePayload.from_zip(archive,MEMBER)
    inputs={'revision':REVISION,'source':baseline.sha256,'source_bytes':baseline.bytes,
            'private':{name:hashlib.sha256(raw).hexdigest()for name,raw in sorted(private.items())},
            'native':{name:hashlib.sha256(raw).hexdigest()for name,raw in sorted(native.items())}}
    output=work/'pc0000-movies.zip'
    state={'source_reused':False,'baseline_temp_bytes':0}
    def produce(target):
        selected=baseline
        if isinstance(baseline,ZipPayload):
            # A compressed ZIP member cannot supply cheap random access. Only
            # a cache miss materializes it, once, before nested ZIP inspection.
            path=work/'movie-source-miss.zip'
            with path.open('xb')as destination:baseline.copy_to(destination)
            selected=FilePayload(path,baseline.bytes,baseline.sha256,baseline.crc32,identity(path.stat()))
            state['baseline_temp_bytes']=baseline.bytes
        pending={}
        with selected.open()as stream,zipfile.ZipFile(stream)as nested:
            for filename,movies,allow_native in(('cardstudio_100_P.pak',private,False),
                                               ('cardstudio_content_100_P.pak',native,True)):
                if not movies:continue
                name='PesMobile/Content/Paks/'+filename
                prior=read_movie_pak(nested.read(name),allow_native=allow_native)if name in nested.namelist()else{}
                changed=False
                for movie,raw in movies.items():
                    if movie in prior:
                        if prior[movie]!=raw:raise ValueError('独立动画资源名冲突：'+movie)
                    else:prior[movie]=raw;changed=True
                if changed:pending[filename]=(name,prior)
        if not pending:state['source_reused']=True;return baseline
        updated={}
        for filename,(name,movies)in pending.items():
            path=work/filename;write_movie_pak(path,movies);updated[name]=FilePayload.from_path(path)
        # Raw-copy unchanged compressed entries, rather than decompressing
        # and recompressing the rest of the 500-MiB nested resource archive.
        replace_entries(selected,target,updated)
        return FilePayload.from_path(target)
    if cache:
        result,report=cache.run_file('movie-package',inputs,produce,output,direct=True)
    else:
        result=produce(output);report={'hit':False,'enabled':False,'kind':'movie-package'}
    return result,{**report,**state,'source_sha256':baseline.sha256,
                   'bytes':result.bytes,'sha256':result.sha256,'streamed':True,
                   'direct_cache_view':bool(result.lease),
                   'result_temp_bytes':0 if report.get('hit')or state['source_reused']else result.bytes}
