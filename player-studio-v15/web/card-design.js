const MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
export function originalCardDate(card){
  if(card?.preset?.sample_date)return card.preset.sample_date;
  const m=card?.source_label?.match(/(\d{1,2}) ([A-Za-z]{3}) '(\d{2})/);
  if(!m||!MONTHS.includes(m[2]))return '';
  const year=Number(m[3])+(Number(m[3])>50?1900:2000);
  return `${year}-${String(MONTHS.indexOf(m[2])+1).padStart(2,'0')}-${m[1].padStart(2,'0')}`;
}
export function formatCardDate(value){
  const m=String(value||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);if(!m||!MONTHS[Number(m[2])-1])return '';
  return `${Number(m[3])} ${MONTHS[Number(m[2])-1]} '${m[1].slice(-2)}`;
}
export function applyCardPreset(project,card){
  const custom=project.native_card?.custom_motion;
  project.native_card=structuredClone(card);if(custom)project.native_card.custom_motion=custom;project.native_card_disabled=false;
  project.card_type=card.card_type;project.card_series=card.native_style==='0601'?'ShowTime':card.card_type;
  project.native_art??={};for(const key of ['background','foreground','full'])project.native_art[key]=null;
  project.appearance.background_image=null;project.appearance.native_overlay_text=true;
  if(project.appearance.card_date===undefined)project.appearance.card_date=originalCardDate(card);
}
