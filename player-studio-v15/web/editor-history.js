// A draft's undo stack belongs to its permanent identity, never to another editor.
export class DraftHistory {
  constructor({read,write,onChange=()=>{},limit=60,clock=()=>performance.now()}) {
    Object.assign(this,{read,write,onChange,limit,clock});this.scope=read()?.uuid??null;this.past=[];this.future=[];this.endGroup();
  }
  reset(){this.scope=this.read()?.uuid??null;this.past=[];this.future=[];this.endGroup();this.onChange();}
  endGroup(){this.key=null;this.time=-Infinity;}
  sync(){if((this.read()?.uuid??null)!==this.scope)this.reset();}
  get canUndo(){this.sync();return !!this.scope&&!!this.past.length;}
  get canRedo(){this.sync();return !!this.scope&&!!this.future.length;}
  commit(mutator,key=null){
    this.sync();const value=this.read();if(!value)return false;
    const before=structuredClone(value),beforeJSON=JSON.stringify(before);
    try{mutator();}catch(error){Object.keys(value).forEach(k=>delete value[k]);Object.assign(value,before);throw error;}
    if(JSON.stringify(value)===beforeJSON)return false;
    const now=this.clock();
    if(!key||key!==this.key||now-this.time>600){this.past.push(before);if(this.past.length>this.limit)this.past.shift();}
    this.future=[];this.key=key;this.time=now;this.onChange();return true;
  }
  move(from,to){
    this.sync();if(!this.scope||!from.length)return false;
    to.push(structuredClone(this.read()));if(to.length>this.limit)to.shift();
    const value=from.pop();this.endGroup();this.write(structuredClone(value));this.onChange();return true;
  }
  undo(){this.sync();return this.move(this.past,this.future);}
  redo(){this.sync();return this.move(this.future,this.past);}
}

export function activeHistory(page,{pack,coach,player}){
  if(page==='packs')return pack;
  if(page==='coaches')return coach;
  return ['profile','abilities','training','skills','motion','card','model','library','personal'].includes(page)?player:null;
}

export function historyShortcut(event){
  if(!(event.ctrlKey||event.metaKey)||event.altKey||event.isComposing)return null;
  const key=event.key.toLowerCase();if(!['z','y'].includes(key))return null;
  const el=event.target,editable=el?.isContentEditable||['INPUT','TEXTAREA','SELECT'].includes(el?.tagName);
  // Search boxes keep their native text undo; actual draft fields use the same history as the toolbar.
  if(editable&&!el?.matches?.('[data-bind],[data-coach-field],[data-coach-portrait],[data-link-field],[data-pack-field],[data-pack-weight],[data-pack-cover-field],[data-custom-field],[data-custom-stat],[data-equipment],[data-booster-slot]'))return null;
  return key==='y'||event.shiftKey?'redo':'undo';
}
