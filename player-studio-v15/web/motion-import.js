// Wait for a background conversion without keeping one HTTP request open.
export async function importCardMovie(api,body,{pause=ms=>new Promise(r=>setTimeout(r,ms)),onState=()=>{}}={}){
 let state=await api('card-motion/import',body);
 const job=state.job_id;if(!job)throw Error('视频任务未创建');
 while(state.phase==='working'){
  onState(state);await pause(700);state=await api('card-motion/status',{job_id:job});
 }
 onState(state);
 if(state.phase==='cancelled')return null;
 if(state.phase!=='done'||!state.result)throw Error(state.message||'视频转换未完成');
 return state.result;
}
