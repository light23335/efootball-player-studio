"""Seven AI-style flags in Player.bin and the 147-parameter card layout.

Native offsets agree with the supplied APK's export_ai_playing_styles.FIELDS.
Owned parameters 63..69 precede the skill block at 70; the three populated
legacy columns (65, 68, 69) agree with all 14,379 complete native card pairs.
The other four columns in the stock catalogue are usually placeholders, so
read preserved Player.bin records first, just as the game does for AI styles.
Lone Wolf is an independent extension: disk bit 687, virtual parameter 151,
and match AI bit 7. Native owned arrays remain exactly 147 parameters.
"""
FIELDS={
 'trickster':{'label':'魔术师','english':'Trickster','bit':616,'parameter':63},
 'mazing_run':{'label':'惊人突破','english':'Mazing Run','bit':625,'parameter':64},
 'speeding_bullet':{'label':'疾速子弹','english':'Speeding Bullet','bit':675,'parameter':65},
 'incisive_run':{'label':'内切突破','english':'Incisive Run','bit':650,'parameter':66},
 'long_ball_expert':{'label':'长球专家','english':'Long Ball Expert','bit':680,'parameter':67},
 'early_cross':{'label':'提前传中手','english':'Early Crosser','bit':351,'parameter':68},
 'long_ranger':{'label':'重炮手','english':'Long Ranger','bit':647,'parameter':69},
}
CUSTOM_SOURCE_BIT=687
CUSTOM_PARAMETER=151
OPTIONS={**FIELDS,'lone_wolf':{'label':'独狼','english':'Lone Wolf','custom':True,
 'description':'优先安全远射；否则带向射位。与内切突破组合时优先内切寻找射位；有弧线落叶射门时优先调整到适合该射门的姿态。'}}


def validate(values):
 if not isinstance(values,list) or any(not isinstance(v,str) or v not in OPTIONS for v in values):
  raise ValueError('AI 比赛风格须从已支持风格中选择')
 return [k for k in OPTIONS if k in values]


def from_record(row):
 if len(row)!=400:raise ValueError('AI 比赛风格的原生球员记录长度不兼容')
 bits=int.from_bytes(row,'little')
 return [k for k,f in FIELDS.items() if (bits>>f['bit'])&1]+(['lone_wolf']if(bits>>CUSTOM_SOURCE_BIT)&1 else [])


def from_payload(payload):
 raw=payload.get('_studio_client_record')
 if raw is not None:
  try:row=bytes.fromhex(raw)
  except (TypeError,ValueError) as exc:raise ValueError('AI 比赛风格的原生球员记录无效') from exc
  return from_record(row)
 if 'ai_playing_styles' in payload:return validate(payload['ai_playing_styles'])
 params=payload.get('_careerplan_base_parameters') or payload.get('parameters') or []
 if len(params)==147:return [k for k,f in FIELDS.items() if params[f['parameter']]==1]
 return None


def write_parameters(params,selected):
 for key,f in FIELDS.items():params[f['parameter']]=int(key in selected)


def restore_payload(payload):
 selected=from_payload(payload)
 if selected is not None:
  payload['ai_playing_styles']=selected
  for key in ('parameters','_careerplan_base_parameters'):
   if len(payload.get(key) or [])==147:
    params=list(payload[key]);write_parameters(params,selected);payload[key]=params
 return payload


def project_value(project,template=None,source_record=None):
 if project.get('ai_playing_styles') is not None:return validate(project['ai_playing_styles'])
 selected=from_payload((project.get('source_player') or {}).get('original_payload') or {})
 if selected is None and source_record is not None:selected=from_record(source_record)
 if selected is None and template is not None:selected=from_payload(template)
 return selected if selected is not None else []
