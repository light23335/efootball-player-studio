const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds={action_change:'动作状态观察',motion_selection:'动作选择',ai_candidate_choice:'AI 候选选择（含盘带）',movement_sample:'移动／盘带轨迹采样',ai_shot_request:'AI 射门请求',ai_shot_power:'AI 射门蓄力',native_diagnostic:'原生入口诊断',trace_heartbeat:'采集心跳',match_start:'比赛开始',match_capture_opened:'本场日志建立',match_state:'比赛状态／名单',match_end:'比赛结束',match_exit:'离开比赛',match_capture_closed:'采集结束',trace_summary:'完整性统计',trace_metadata_overrun:'比赛状态记录缺口'};
export async function readActionLog(file,limit=10000){
 if(file.size>64*1024*1024)throw new Error('请选择单个日志分卷（最大 64 MB）。');
 const reader=file.stream().getReader(),decoder=new TextDecoder();let pending='',total=0,invalid=0,rows=[],header=null,gapEvents=0,lostEvents=0,lossUnknown=false;
 const line=text=>{if(!text.trim())return;try{const value=JSON.parse(text);if(!value||typeof value!=='object'||Array.isArray(value))throw new Error();
  if(value.event==='trace_header'){if(![1,2,3].includes(value.version))throw new Error();header=value;return;}
  if(!kinds[value.event]&&!['trace_overrun','trace_contention','trace_reset'].includes(value.event))throw new Error();
  if(['trace_overrun','trace_contention','trace_reset'].includes(value.event)){gapEvents++;if(Number.isFinite(value.lost_events))lostEvents+=value.lost_events;if(value.count_is_lower_bound)lossUnknown=true;}
  total++;rows.push(value);if(rows.length>limit*2)rows=rows.slice(-limit);
 }catch{invalid++;}};
 while(true){const {done,value}=await reader.read();if(done)break;pending+=decoder.decode(value,{stream:true});const parts=pending.split('\n');pending=parts.pop();for(const part of parts)line(part);}
 pending+=decoder.decode();line(pending);rows=rows.slice(-limit);
 if(!header&&!total)throw new Error('没有可识别的比赛动作记录。');
 return {rows,total,invalid,retained:rows.length,header,gapEvents,lostEvents,lossUnknown};
}
export function filterActions(rows,query='',team='',kind=''){
 const needle=query.trim().toLowerCase();
 return rows.filter(row=>(!team||String(row.team)===team)&&(!kind||row.event===kind)&&(!needle||JSON.stringify(row).toLowerCase().includes(needle)));
}
export function actionRow(row){
 if(!kinds[row.event])return `<div class="migration-status error">日志记录缺口：${esc(row.event)} · ${row.count_is_lower_bound?'存在未计数的丢失事件':esc(row.lost_events??'计数器重置')}</div>`;
 if(!['action_change','motion_selection','ai_shot_request','ai_shot_power','ai_candidate_choice','movement_sample'].includes(row.event))return `<div class="player-option"><div><strong>${esc(kinds[row.event])}</strong><small>${esc(row.utc||'')} · 比赛 ${esc(row.match_id||row.game_id||'未绑定')}</small><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(row,null,2).slice(0,6000))}</pre></div></div>`;
 const player=row.player_name||'球员 ID '+(row.player_id||'未知');
 const where=`队伍 ${row.team===0?'A':'B'} · 第 ${Number(row.team_slot??row.slot??0)+1} 个场上槽位`;
 const title=row.event==='ai_candidate_choice'?`${row.candidate?.original_name} → ${row.candidate?.selected_name}`:row.event==='movement_sample'?'移动轨迹（不单独证明控球）':row.event==='motion_selection'?`${row.motion?.name||'原生动作族 '+row.original_type} · ${row.motion?.selection_succeeded?'选择成功':'选择失败'}`:row.action?.name||'原生动作 '+row.action?.id;
 const power=Number.isFinite(row.power_after)?Math.round(row.power_after*100)+'%':'未采集';
 const change=row.event==='ai_shot_request'?` · ${row.original_type_name||row.original_type} → ${row.selected_type_name||row.selected_type}`:row.event==='ai_shot_power'?` · 力度 ${Number.isFinite(row.power_before)?Math.round(row.power_before*100)+'%':'未采集'} → ${power}`:'';
 return `<div class="player-option"><div><strong>${esc(player)} · ${esc(title)}</strong><small>${esc(where)} · 帧 ${esc(row.frame)} · ${esc(kinds[row.event])}</small><small>请求：${esc(row.request?.name)}${esc(change)} · 蓄力 ${esc(power)} · 技能：${esc(row.skills?.join('、')||'无对应射门技能')}</small><small>${esc(row.utc||'')} · ${esc(row.stage||'')} · 原生动作 ${esc(row.action?.id)} / 请求 ${esc(row.request?.id)}:${esc(row.request?.subtype)}</small></div></div>`;
}
export function attachActionLogView(parent,enabled){
 const panel=document.createElement('section');panel.className='panel';
 panel.innerHTML=`<div class="panel-title"><h3>比赛动作日志（V17）</h3></div><div class="panel-body"><label class="switch-label"><input type="checkbox" data-game-enabled="action_trace" ${enabled?'checked':''}>记录双方球员动作（试验，默认关闭）</label><p class="note">诊断版：重新生成游戏 APK 后生效。记录入口与过滤计数、5 秒心跳、原生动作状态、动作选择、移动轨迹、内切／独狼候选选择及 AI 射门请求／力度的前后变化。身份未确认只保留最小诊断。动作选择成功不代表最终播放；全场覆盖仍待实机验收。日志只观察，不参与决策。</p><details><summary>打开与筛选动作日志</summary><p class="note">游戏日志保存在游戏私有目录 outputs/efootball/player-actions；安卓每 15 秒定时、安静约 3 秒及比赛结束／退出时，会尝试导出到“下载 / PlayerStudioLogs”。选择一个 .jsonl 分卷查看，PC 和手机都支持。页面最多保留末尾 10,000 条；完整文件不修改。</p><input type="file" accept=".jsonl,.json,application/json,application/x-ndjson" aria-label="选择比赛动作日志" data-action-log-file><div class="field-grid"><input type="search" class="input" placeholder="球员姓名／球员 ID／动作" data-action-log-query><select aria-label="筛选球队" data-action-log-team><option value="">双方球员</option><option value="0">队伍 A</option><option value="1">队伍 B</option></select><select aria-label="筛选日志类型" data-action-log-kind><option value="">所有记录</option><option value="action_change">动作切换</option><option value="motion_selection">动作选择</option><option value="ai_candidate_choice">AI 盘带／传球／射门选择</option><option value="movement_sample">移动轨迹</option><option value="ai_shot_request">射门请求前后</option><option value="ai_shot_power">射门力度前后</option><option value="trace_heartbeat">入口计数与心跳</option><option value="native_diagnostic">过滤诊断</option><option value="match_state">比赛状态与名单</option><option value="trace_summary">完整性统计</option><option value="trace_overrun">缓冲区丢失</option></select></div><p class="note" data-action-log-status>尚未打开日志。</p><button class="button secondary" data-action-log-export disabled>保存筛选后的日志</button><div class="export-list" data-action-log-list style="max-height:520px;overflow:auto"></div></details></div>`;
 parent.append(panel);let loaded=null,filtered=[];
 const draw=()=>{if(!loaded)return;filtered=filterActions(loaded.rows,panel.querySelector('[data-action-log-query]').value,panel.querySelector('[data-action-log-team]').value,panel.querySelector('[data-action-log-kind]').value);
  panel.querySelector('[data-action-log-status]').textContent=`文件共 ${loaded.total} 条，保留末尾 ${loaded.retained} 条，筛选 ${filtered.length} 条；${loaded.invalid} 条无法解析。显示最近 200 条。`+(loaded.gapEvents?` 文件有 ${loaded.gapEvents} 条缺口报告，至少丢失 ${loaded.lostEvents} 条${loaded.lossUnknown?'，另有未计数事件':''}；没有记录不代表没有执行。`:'');
  panel.querySelector('[data-action-log-list]').innerHTML=filtered.slice(-200).reverse().map(actionRow).join('')||'<p class="note">没有匹配记录。</p>';
  panel.querySelector('[data-action-log-export]').disabled=!filtered.length;
 };
 panel.oninput=e=>{if(e.target.matches('[data-action-log-query]')){e.stopPropagation();draw();}};
 panel.onchange=async e=>{if(e.target.matches('[data-game-enabled]'))return;e.stopPropagation();
  if(e.target.matches('[data-action-log-file]')){const file=e.target.files?.[0];if(!file)return;try{loaded=await readActionLog(file);}catch(error){panel.querySelector('[data-action-log-status]').textContent=error.message;return;}}
  draw();
 };
 panel.querySelector('[data-action-log-export]').onclick=e=>{e.stopPropagation();if(!filtered.length)return;
  const header=loaded.header||{event:'trace_header',version:1};const blob=new Blob([[header,...filtered].map(v=>JSON.stringify(v)).join('\n')+'\n'],{type:'application/x-ndjson'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='比赛动作-筛选.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
 return panel;
}
