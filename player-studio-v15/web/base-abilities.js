// Keep level-one editing separate from the game's training/booster caps.
export const BASE_ABILITY_MIN=40,BASE_ABILITY_MAX=103;
export function normalizeBaseAbility(value,defaultValue=65){
  if(!['number','string'].includes(typeof value)||typeof value==='string'&&!value.trim())return defaultValue;
  const number=Number(value);
  return Number.isFinite(number)?Math.max(BASE_ABILITY_MIN,Math.min(BASE_ABILITY_MAX,Math.trunc(number))):defaultValue;
}
