from pathlib import Path
import json
root=Path(__file__).resolve().parents[1];path=root/'player-studio/resources/native-card-presets.json'
catalog=json.loads(path.read_text(encoding='utf8'));audit=json.loads((root/'.work/studio-qa/v14-all-bt-epic-audit.json').read_text(encoding='utf8'))
empty=set(audit.get('emptyDesigns',[]))
for row in catalog['rows']:
    if row['id'] in empty:row.update(available=False,unavailable_reason='原包缺少可独立使用的空白设计图层，未用黑底替代完整卡面')
path.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')),encoding='utf8')
print('Incomplete designs',len(empty))
