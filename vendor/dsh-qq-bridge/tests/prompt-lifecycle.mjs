import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const old = { home: process.env.DSH_HOME, fetch, setTimeout, clearTimeout }
const home = mkdtempSync(join(tmpdir(), 'qq-prompt-lifecycle-')); process.env.DSH_HOME = home
writeFileSync(join(home, 'qq-bridge-config.json'), JSON.stringify({ 总开关: true, 人设开: true, 人设: '隔离测试的人设', NapCat: 'http://napcat.invalid',
  绑定: ['A', 'B'].map((k, i) => ({ 类型: '私聊', 号码: String(123+i), 会话: 'session-'+k, 偏好: { nickname: '称呼'+k } })) }))
globalThis.fetch = async () => ({ json: async () => ({ status:'ok', retcode:0, data:{ messages:[] } }) })
globalThis.setTimeout = () => ({}); globalThis.clearTimeout = () => {}
let release, tick
const hold = new Promise(r => { release = r }), agents = new Map(), prompts = new Map(), effects = [], errors = []
for (const k of ['A','B']) {
  const sections = new Map(); prompts.set(k, sections)
  const sp = { getSectionOrder: () => 1,
    section(s) { if (sections.has(s.name)) { errors.push(s.name); throw Error('重复装配') }; sections.set(s.name,s); return () => sections.delete(s.name) },
    async assemble() { await hold; return { sections: [...sections.values()] } },
  }
  agents.set('session-'+k, { session:{id:'session-'+k}, ctx:{get:n=>n==='systemPrompt'?sp:undefined, tools:{register:()=>()=>{}}}, followup(){assert.fail('不应调用模型')} })
}
try {
  const host = await import('../lib/host.js')
  host.apply({ effect(fn){effects.push(fn())}, on:()=>()=>{}, interval(fn){tick=fn;return()=>{}}, webServer:{register(){}}, agents:{get:id=>agents.get(id)}, logger:{info(){}}, get(){} })
  await tick(); await tick()
  const before = [...prompts.values()].reduce((sum,m)=>sum+m.size,0)
  effects.splice(0).reverse().forEach(fn=>fn?.())
  const during = [...prompts.values()].reduce((sum,m)=>sum+m.size,0)
  release()
  for (let i=0;i<20;i++) await new Promise(setImmediate)
  const after = [...prompts.values()].reduce((sum,m)=>sum+m.size,0)
  assert.equal(before,2,'首个会话的两段提示应已注册并等待装配')
  assert.deepEqual({ errors, during, after }, { errors:[], during:0, after:0 }, '并发补挂不能重复，卸载应立即撤销，异步后续不能复活任何会话的提示')
  console.log('提示生命周期：并发补挂去重、装配中卸载立即撤销、后续会话不再挂载通过')
} finally {
  release(); effects.reverse().forEach(fn=>fn?.()); globalThis.fetch=old.fetch;globalThis.setTimeout=old.setTimeout;globalThis.clearTimeout=old.clearTimeout
  if(old.home===undefined)delete process.env.DSH_HOME;else process.env.DSH_HOME=old.home
  rmSync(home,{recursive:true,force:true})
}
