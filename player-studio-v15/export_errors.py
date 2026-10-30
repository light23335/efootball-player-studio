"""Precise, composable export diagnostics, shared by PC and Android."""
from contextlib import contextmanager
from functools import wraps


def subject(value):
    if not isinstance(value,dict):return str(value or '未命名资料')
    identity=value.get('identity') or {}
    if not isinstance(identity,dict):identity={}
    name=identity.get('name') or value.get('name') or value.get('display_name') or value.get('target') or value.get('path') or '未命名资料'
    ident=value.get('package_id') or value.get('uuid') or value.get('id') or identity.get('package_id')
    return str(name)+((' [身份 '+str(ident)+']') if ident is not None else '')


class ExportError(ValueError):
    def __init__(self,kind,item,stage,cause):
        self.contexts=[{'kind':str(kind),'subject':subject(item),'stage':str(stage)}]
        if isinstance(cause,ExportError):
            self.contexts.extend(cause.contexts);self.reason=cause.reason;self.original_type=cause.original_type
        else:
            self.reason=str(cause) or type(cause).__name__;self.original_type=type(cause).__name__
        labels=['%s「%s」／%s'%(r['kind'],r['subject'],r['stage']) for r in self.contexts]
        super().__init__('导出失败：'+' → '.join(labels)+'。原因：'+self.reason)


@contextmanager
def export_context(kind,item,stage):
    try:yield
    except Exception as cause:
        raise ExportError(kind,item,stage,cause) from cause


def exported(kind,stage,identify):
    def decorate(function):
        @wraps(function)
        def run(*args,**kwargs):
            try:item=identify(*args,**kwargs)
            except Exception:item=function.__qualname__
            with export_context(kind,item,stage):return function(*args,**kwargs)
        return run
    return decorate


def call(kind,item,stage,function,*args,**kwargs):
    with export_context(kind,item,stage):return function(*args,**kwargs)


def failure(error,kind,item,stage):
    return error if isinstance(error,ExportError) else ExportError(kind,item,stage,error)
