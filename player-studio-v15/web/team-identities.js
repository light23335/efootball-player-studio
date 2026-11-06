// Presentation aliases never migrate stored identity text or design receipts.
let teams=new Map();
export function setTeamOptions(rows){teams=new Map((rows||[]).map(r=>[Number(r.id),r]));}
export function teamLabel(identity){return teams.get(Number(identity?.team_id))?.name||identity?.team||'';}
export function identitySelection(value,kind,options,current){
 const rows=options[kind]||[],field=kind==='nation'?'nationality':'team',idField=kind==='nation'?'nation_id':'team_id';
 const exact=rows.find(r=>r.name+' · #'+r.id===value);
 const matches=rows.filter(r=>[r.name,r.name_en,r.source_name,r.source_name_en,...(r.aliases||[])].includes(value));
 const row=exact||(matches.length===1?matches[0]:null);
 if(!row)return {id:null,stored:value,display:value};
 // Selecting the already-selected club is a pure display operation, even if
 // this old project predates aliases or uses a hand-written historical name.
 return {id:row.id,stored:Number(current[idField])===Number(row.id)?current[field]:(row.source_name||row.name),display:row.name};
}
