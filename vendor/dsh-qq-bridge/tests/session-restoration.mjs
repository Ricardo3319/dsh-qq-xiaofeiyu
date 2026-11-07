import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const old = { home: process.env.DSH_HOME, fetch, now: Date.now, setTimeout, clearTimeout }
const home = mkdtempSync(join(tmpdir(), 'qq-session-restoration-'))
process.env.DSH_HOME = home
let now = 1794000000000, tick, release, fail = true
Date.now = () => now
globalThis.setTimeout = () => ({})
globalThis.clearTimeout = () => {}
const file = join(home, 'qq-bridge-config.json')
const config = { 总开关: true, 试运行: false, NapCat: 'http://napcat.invalid', 绑定: [
  { 类型: '私聊', 号码: '123', 会话: 'session-P' },
  { 类型: '群', 号码: '456', 会话: 'session-G' },
  { 类型: '群', 号码: '789', 会话: 'session-H', 开: false },
  { 类型: '群', 号码: '888', 会话: 'session-archived' },
] }
const save = () => writeFileSync(file, JSON.stringify(config)); save()
const agents = new Map(), calls = [], effects = [], routes = new Map(), sent = []
const makeAgent = id => {
  const registered = new Map()
  const agent = { session: { id }, registered, ctx: { tools: { register(t) { registered.set(t.name,t); return () => registered.delete(t.name) } } }, followup() { throw new Error('恢复会话不能提交消息') } }
  agents.set(id,agent); return agent
}
const gate = new Promise(r => { release = r })
const controller = { async resolveAgent(id) {
  calls.push(id)
  if (id === 'session-P') await gate
  if (id === 'session-G' && fail) return { error: { message: '模拟临时恢复失败' } }
  return { agent: makeAgent(id) }
} }
globalThis.fetch = async (url,opt) => {
  if (url.includes('/send_')) sent.push(JSON.parse(opt.body))
  return { json: async () => ({ status: 'ok', retcode: 0, data: url.endsWith('/get_login_info') ? { user_id: 10001 } : { messages: [] } }) }
}
const settle = async () => { for(let i=0;i<25;i++) await new Promise(setImmediate) }
try {
  const host = await import('../lib/host.js')
  host.apply({ effect(fn) { effects.push(fn()) }, on: () => () => {},
    webServer: { register(o) { routes.set(o.path,o.handler) } }, interval(fn) { tick=fn; return () => {} },
    agents: { get: id => agents.get(id) }, sessions: { list: () => config.绑定.map(b => ({ id:b.会话 })), flush: async () => {} },
    workspaceRegistry: { archivedSessionIds: ['session-archived'] },
    attachments: { admitPromptContent:c=>c }, logger: { info() {} },
    get: name => name==='sessionController' ? controller : name==='connection' ? { requestRejection:()=>undefined } : undefined })
  await tick(); await tick()
  assert.deepEqual(calls,['session-P'], '正在恢复时不能再发起一份恢复任务')
  let state
  await routes.get('/dsh-qq-bridge/state')([], { end:s=>{state=JSON.parse(s)} })
  assert.equal(state.绑定[0].活着,false,'磁盘会话不能冒充已加载 agent')
  release(); await settle(); await tick()
  assert.deepEqual(calls,['session-P','session-G'])
  const first=agents.get('session-P')
  assert.ok(first.registered.has('qq_chat_preferences'))
  assert.ok(!calls.includes('session-H') && !calls.includes('session-archived'))
  await tick(); assert.equal(calls.length,2,'临时失败不能每两秒重试')
  now+=60000; config.试运行=true; save(); await tick(); await settle()
  assert.equal(calls.length,2,'试运行不能恢复会话')
  config.试运行=false; config.总开关=false; save(); await tick(); await settle()
  assert.equal(calls.length,2,'关闭不能恢复会话')
  config.总开关=true; save(); fail=false; await tick(); await settle(); await tick()
  assert.equal(calls.length,3)
  assert.ok(agents.get('session-G').registered.has('qq_chat_preferences'))
  const replacement=makeAgent('session-P'); await tick()
  assert.ok(replacement.registered.has('qq_chat_preferences'),'替换实例后工具必须重新挂载')
  assert.ok(!first.registered.has('qq_chat_preferences'),'旧实例的工具应卸下')
  await routes.get('/dsh-qq-bridge/state')([], { end:s=>{state=JSON.parse(s)} })
  assert.equal(state.绑定[0].活着,true)
  assert.equal(state.绑定[1].活着,true)
  assert.equal(sent.length,0,'只恢复会话，不发送测试消息')
  effects.splice(0).forEach(fn=>fn?.()); now+=60000; agents.delete('session-G'); await tick()
  assert.equal(calls.length,3,'停止后不能再恢复')
  console.log('会话恢复：并发去重、已有绑定/停用/归档、失败退避、试运行/关闭/停止、真实加载状态、工具换实例补挂通过')
} finally {
  effects.forEach(fn=>fn?.())
  globalThis.fetch=old.fetch; Date.now=old.now; globalThis.setTimeout=old.setTimeout; globalThis.clearTimeout=old.clearTimeout
  if(old.home===undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME=old.home
  rmSync(home,{recursive:true,force:true})
}
