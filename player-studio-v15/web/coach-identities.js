export const identityField=kind=>kind==='nation'?'nation_id':'team_id';
export function coachIdentity(row){return {nation_id:row?.nation_id??0,team_id:row?.team_id??row?.raw_payload?.initial_base_team_id??0,native_source_id:row?.type==='native'?String(row.id):row?.native_source_id??null};}
export function identityLabel(row,kind,options){
 const id=row[identityField(kind)]??0;
 if(!id)return kind==='nation'?(row.identity_available===false?'国籍未读取':'未设置国籍'):(row.team_source==='unavailable'?'原包未提供俱乐部':'无俱乐部');
 const found=(options[kind]||[]).find(r=>r.id===id);
 return found?.name||found?.name_en||`编号 ${id}（当前库暂无名称）`;
}
export function identityMatches(options,kind,query){
 const q=query.trim().toLocaleLowerCase().replace(/^#/,'');
 return (options[kind]||[]).filter(r=>r.id>0&&r.id<=(kind==='nation'?511:131071)&&(!q||String(r.id)===q||[r.name,r.name_en].join(' ').toLocaleLowerCase().includes(q)));
}
