export async function exportStep(name,step,operation){
  try{return await operation();}
  catch(cause){
    if(String(cause?.message||'').startsWith('导出失败：'))throw cause;
    const error=new Error(`导出失败：${name||'未命名球员'}／${step}。原因：${cause?.message||cause?.name||String(cause)}`,{cause});
    throw error;
  }
}
