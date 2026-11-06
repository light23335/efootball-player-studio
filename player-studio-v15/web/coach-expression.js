// Preview controls share the player's HeadTools path. Values are transient.
export function expressionPanel(scope,custom,preserve=false,test={},disabled=false){
  const lock=disabled?'disabled':'';
  const optionLock=disabled||!custom?'disabled':'';
  return `<div class="coach-expression"><label class="switch-label"><input type="checkbox" data-coach-expression="${scope}" ${preserve?'checked':''} ${optionLock}>导入游戏时保持导入表情（自制头模）</label><p class="note">开启后保护下颌和眼睑，头颈仍随游戏动作运动；关闭后使用导入的面部权重。原版头模沿用原版表情。</p><div class="field-grid">${[['jaw','张嘴检查'],['blink','闭眼检查']].map(([key,label])=>`<label class="field"><span>${label}</span><input type="range" min="0" max="1" step=".01" value="${Number(test[key])||0}" data-coach-expression-test="${scope}" data-expression-kind="${key}" ${lock}></label>`).join('')}</div><p class="note">检查仅临时使用原始面部权重，归零恢复导出效果，不改变保持表情开关。无对应骨骼权重时无法产生相应动作。${custom?'此选项随这名教练保存；新导入默认保持表情。':'导入自制头模后，此选项随该教练保存。'}</p><p class="note" data-coach-expression-notice="${scope}"></p></div>`;
}

export function expressionSpec(result){
  return result?.head_preview||{export_url:result.url,raw_url:result.url,anchors:{},original_game_face:result.report?.mode!=='custom'};
}

export function previewModel(result,preserve=false){
  const custom=result.report?.mode==='custom';
  return {model:{asset:result.asset_id,native_source:custom?null:{path:result.path||result.template_path},
    preserve_expression:preserve,neck_seam:false,scale:1,rotation:0,morphs:{}}};
}

export function applyExpressionTest(viewer,test,notice){
  viewer?.setHeadTest(test);
  if(!notice)return;
  const names=new Set();viewer?.headTools?.base.forEach(poses=>poses.forEach(p=>names.add(p.bone.name)));
  const missing=[];
  if(test.jaw>0&&!names.has('skf_jaw'))missing.push('张嘴');
  if(test.blink>0&&![...names].some(n=>n.startsWith('skf_eyelid_')))missing.push('闭眼');
  notice.textContent=missing.length?'当前模型没有可用的'+missing.join('／')+'骨骼；无法检查对应动作。':
    test.jaw>0||test.blink>0?'正在临时检查原始面部权重，不改变保存设置。':'';
}
