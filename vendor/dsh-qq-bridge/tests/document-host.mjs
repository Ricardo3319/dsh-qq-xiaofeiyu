import assert from 'node:assert/strict'
import { mkdtempSync,writeFileSync,rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const old={home:process.env.DSH_HOME,fetch,now:Date.now,setTimeout,clearTimeout}
const home=mkdtempSync(join(tmpdir(),'qq-document-host-'));process.env.DSH_HOME=home
let now=1794000000000,tick,downloadGate=null,downloads=0
Date.now=()=>now;globalThis.setTimeout=()=>({});globalThis.clearTimeout=()=>{}
const file=join(home,'qq-bridge-config.json')
const config={总开关:true,试运行:false,收图:false,合并窗口秒:0,回复冷却秒:0,NapCat:'http://napcat.invalid',令牌:'fixture-only-token',绑定:[
 {类型:'群',号码:'111',会话:'session-A',只听点名:true},{类型:'群',号码:'222',会话:'session-B',只听点名:true},
 {类型:'私聊',号码:'333',会话:'session-C'}]}
const save=()=>writeFileSync(file,JSON.stringify(config));save()
writeFileSync(join(home,'qq-bridge-state.json'),JSON.stringify({上次:{'群:111':now/1000-60,'群:222':now/1000-60,'私聊:333':now/1000-60},已转:[]}))
const effects=[],tools=new Map(),agents=new Map(),incoming=[],requests=[]
for(const k of ['A','B','C']) {const ts=new Map();tools.set(k,ts);agents.set('session-'+k,{session:{id:'session-'+k},ctx:{tools:{register(t){ts.set(t.name,t);return()=>ts.delete(t.name)}}},followup(m){incoming.push({k,m})}})}
const row=(id,user=123)=>({message_id:id,time:now/1000,user_id:user,sender:{nickname:'测试'},message:[{type:'file',data:{file_id:'file-'+id,name:'资料.txt',file_size:80}}]})
const messages=new Map([['111',[row(1)]],['222',[row(2)]],['333',[row(3,333)]]])
globalThis.fetch=async(url,opt)=>{
 if(String(url).startsWith('https://qq-file.example')) {downloads++;assert.equal(opt.headers,undefined);if(downloadGate)await downloadGate;return new Response('结论：周五完成。\n负责人：未定。')}
 requests.push(String(url).split('/').at(-1));const body=JSON.parse(opt.body||'{}');let data={}
 if(url.endsWith('/get_login_info'))data={user_id:10001}
 else if(url.endsWith('_msg_history'))data={messages:messages.get(String(body.group_id||body.user_id))||[]}
 else if(url.endsWith('_file_url')) {
   assert.equal(opt.headers.authorization,'Bearer fixture-only-token')
   if(body.file_id==='file-3') {assert.equal(body.user_id,'333');assert.ok(url.endsWith('/get_private_file_url'))}
   else {assert.equal(body.group_id,'111');assert.ok(url.endsWith('/get_group_file_url'))}
   data={url:'https://qq-file.example/file'}
 } else assert.fail('文档功能不应产生额外发送请求：'+url)
 return {json:async()=>({status:'ok',retcode:0,data})}
}
const read=k=>tools.get(k).get('qq_read_document')
try {
 const host=await import('../lib/host.js')
 host.apply({effect(fn){effects.push(fn())},on:()=>()=>{},webServer:{register(){}},interval(fn){tick=fn;return()=>{}},agents:{get:id=>agents.get(id)},sessions:{flush:async()=>{}},attachments:{admitPromptContent:c=>c},logger:{info(){}},get(){}})
 await tick()
 assert.equal(downloads,0)
 assert.equal(incoming.filter(x=>x.k==='A').length,0,'未点名群文件只登记，不自动总结')
 assert.equal(incoming.filter(x=>x.k==='C').length,1,'私聊纯文件不能再静默丢掉')
 assert.match(JSON.stringify(incoming[0]),/doc-3-0/)
 assert.match(JSON.stringify(incoming[0]),/尚未读取/)
 assert.equal((await read('A').execute({})).documents[0].document_id,'doc-1-0')
 assert.equal((await read('B').execute({document_id:'doc-1-0'})).ok,false)
 assert.equal((await read('C').execute({document_id:'doc-3-0'})).ok,true)
 const result=await read('A').execute({document_id:'doc-1-0'})
 assert.equal(result.ok,true);assert.match(result.content,/负责人：未定/);assert.equal(result.line_start,1)
 assert.equal(requests.filter(r=>r==='get_group_file_url').length,1)
 assert.equal(requests.filter(r=>r==='get_private_file_url').length,1)
 config.试运行=true;save();assert.equal((await read('A').execute({})).ok,false);await tick()
 config.试运行=false;save();assert.equal((await read('A').execute({})).documents.length,0)
 now+=1000;messages.set('111',[row(4)]);await tick()
 let release;downloadGate=new Promise(r=>{release=r})
 const pending=read('A').execute({document_id:'doc-4-0'})
 await new Promise(setImmediate);config.绑定[0].开=false;save();await tick();release()
 assert.equal((await pending).ok,false)
 const privateReader=read('C')
 effects.splice(0).forEach(fn=>fn?.())
 assert.equal(read('C'),undefined,'卸载后应移除工具注册')
 assert.equal((await privateReader.execute({})).ok,false,'卸载前取得的旧句柄也应拒绝读取')
 console.log('文档宿主：注册、群文件不自动唤醒、私聊纯文件入站、跨聊天隔离、群/私聊文件接口、凭据隔离、试运行/停用/停止通过')
} finally {effects.forEach(fn=>fn?.());globalThis.fetch=old.fetch;Date.now=old.now;globalThis.setTimeout=old.setTimeout;globalThis.clearTimeout=old.clearTimeout;if(old.home===undefined)delete process.env.DSH_HOME;else process.env.DSH_HOME=old.home;rmSync(home,{recursive:true,force:true})}
