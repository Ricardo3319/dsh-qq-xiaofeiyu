import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const old={home:process.env.DSH_HOME,fetch,setTimeout,clearTimeout}
const home=mkdtempSync(join(tmpdir(),'qq-tool-lifecycle-'));process.env.DSH_HOME=home
const config={总开关:true,试运行:false,NapCat:'http://napcat.invalid',绑定:[
 {类型:'群',号码:'111',会话:'session-G',门槛:true},
 {类型:'群',号码:'222',会话:'session-G',门槛:true},
]}
const save=()=>writeFileSync(join(home,'qq-bridge-config.json'),JSON.stringify(config));save()
globalThis.setTimeout=()=>({});globalThis.clearTimeout=()=>{}
globalThis.fetch=async()=>({json:async()=>({status:'ok',retcode:0,data:{messages:[]}})})
let tick,agent
const effects=[],errors=[],failures=[]
const check=(label,value)=>{if(!value)failures.push(label)}
const makeAgent=()=>{
 const tools=new Map()
 return {session:{id:'session-G'},tools,ctx:{tools:{
   register(t){if(tools.has(t.name))throw Error('already registered: '+t.name);tools.set(t.name,t);return()=>{if(tools.get(t.name)===t)tools.delete(t.name)}}
 }},followup(){throw Error('测试不能发起模型回合')}}
}
try {
 const host=await import('../lib/host.js')
 const mount=()=>host.apply({effect(fn){effects.push(fn())},on:()=>()=>{},webServer:{register(){}},interval(fn){tick=fn;return()=>{}},
  agents:{get:id=>['G','session-G'].includes(id)?agent:undefined},sessions:{flush:async()=>{}},attachments:{admitPromptContent:c=>c},
  logger:{info(s){if(s.includes('already registered'))errors.push(s)}},get(){}})
 agent=makeAgent();mount();await tick()
 const names=['qq_reply_gate','qq_space_list','qq_chat_preferences','qq_read_document']
 for(const n of names)assert.ok(agent.tools.has(n),'初次应挂载 '+n)
 await tick();assert.equal(errors.length,0,'共享绑定/重复心跳不应重复注册')
 const first=agent;agent=makeAgent();await tick()
 for(const n of names)check('换实例后漏挂 '+n,agent.tools.has(n))
 check('旧实例仍保留工具',first.tools.size===0)
 config.绑定[0].开=false;save();await tick()
 check('同会话仍有启用绑定时应保留工具',agent.tools.has('qq_chat_preferences'))
 config.绑定[1].开=false;save();await tick()
 check('所有绑定停用后仍保留工具',agent.tools.size===0)
 config.绑定[0].开=true;save();await tick()
 const before=agent.tools.get('qq_read_document')
 effects.splice(0).reverse().forEach(fn=>fn?.())
 check('卸载后仍保留工具',agent.tools.size===0)
 check('卸载前取得的旧文档句柄仍可读取',(await before.execute({})).ok===false)
 mount();await tick()
 check('同实例重载没有换成新工具',agent.tools.get('qq_read_document')!==before)
 check('重载重复注册报错',errors.length===0)
 effects.splice(0).reverse().forEach(fn=>fn?.())
 check('再次卸载仍有残留',agent.tools.size===0)
 assert.deepEqual(failures,[])
 console.log('工具生命周期：三类工具换实例、共享绑定去重、停用撤销、插件卸载/同实例重载通过')
} finally {
 effects.reverse().forEach(fn=>fn?.());globalThis.fetch=old.fetch;globalThis.setTimeout=old.setTimeout;globalThis.clearTimeout=old.clearTimeout
 if(old.home===undefined)delete process.env.DSH_HOME;else process.env.DSH_HOME=old.home
 rmSync(home,{recursive:true,force:true})
}
