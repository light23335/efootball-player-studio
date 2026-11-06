"""Real club labels for editor display/search only. Never edit game records."""
import copy,json
from functools import lru_cache
from studio_resources import bundled_resources

@lru_cache(maxsize=1)
def aliases():return json.loads((bundled_resources()/'real-team-names.json').read_text('utf8'))['teams']


def display(row):
    out=copy.deepcopy(row)
    if row.get('kind')!='team':return out
    found=aliases().get(str(row['id']))
    # An ID alone is not enough: another data source may reuse/rename a team.
    if not found or row.get('name_en')!=found['source_name_en']:return out
    out.update(name=found['name'],name_en=found['name_en'],source_name=row['name'],source_name_en=row['name_en'])
    out['aliases']=list(dict.fromkeys([row['name'],row['name_en'],found['name'],found['name_en']]))
    return out
