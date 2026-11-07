import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const old = { home: process.env.DSH_HOME, fetch: globalThis.fetch,
  setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout }
const home = mkdtempSync(join(tmpdir(), 'qq-memory-host-'))
process.env.DSH_HOME = home
const config = { 总开关: true, 试运行: false, 收图: false, NapCat: 'http://synthetic.invalid',
  绑定: [
    { 类型: '群', 号码: '111', 会话: 'session-A' },
    { 类型: '群', 号码: '222', 会话: 'session-B' },
    { 类型: '私聊', 号码: '333', 会话: 'session-C' },
    { 类型: '群', 号码: '444', 会话: 'session-shared' },
    { 类型: '群', 号码: '555', 会话: 'session-shared' },
  ] }
const save = () => writeFileSync(join(home, 'qq-bridge-config.json'), JSON.stringify(config))
save()
const memoryFile = join(home, 'qq-bridge-memory.json')
writeFileSync(memoryFile, JSON.stringify({ version: 1, 条目: [
  { 说: '小明喜欢蓝色', 类: '事实', 来源: '群', 哪: '111', 时: Date.now() },
  { 说: '小明喜欢蓝色杯子', 类: '事实', 来源: '群', 哪: '111', 时: Date.now() },
  { 说: '小明喜欢蓝色', 类: '事实', 来源: '群', 哪: '222', 时: Date.now() },
  { 说: '小明喜欢蓝色', 类: '事实', 来源: '私聊', 哪: '333', 时: Date.now() },
] }))
globalThis.setTimeout = () => ({})
globalThis.clearTimeout = () => {}
globalThis.fetch = async () => ({ ok: true, json: async () => ({ status: 'ok', data: { user_id: 10001, messages: [] } }) })
let tick, bridge
const toolsets = new Map(), agents = new Map()
for (const sid of ['session-A', 'session-B', 'session-C', 'session-shared']) {
  const tools = new Map()
  toolsets.set(sid, tools)
  agents.set(sid, { session: { id: sid }, ctx: { tools: {
    register(tool) { tools.set(tool.name, tool); return () => tools.delete(tool.name) },
  } }, followup() {} })
}
try {
  const host = await import('../lib/host.js')
  bridge = host.apply({ effect(fn) { return fn() }, on: () => () => {},
    webServer: { register() {} }, interval(fn) { tick = fn; return () => {} },
    agents: { get: id => agents.get(id) }, sessions: { flush: async () => {} },
    attachments: { admitPromptContent: c => c }, logger: { info() {} }, get() {},
  })
  await tick()
  const a = toolsets.get('session-A'), b = toolsets.get('session-B'), c = toolsets.get('session-C')
  for (const name of ['list_common', 'update_common', 'forget_common', 'remember_common']) assert.ok(a.has(name), name)
  const listed = await a.get('list_common').execute({})
  assert.equal(listed.total, 2)
  assert.equal((await c.get('list_common').execute({})).total, 1)
  assert.equal((await toolsets.get('session-shared').get('list_common').execute({})).ok, false, '来源不明时不能猜第一个绑定')
  const own = listed.results.find(x => x.说 === '小明喜欢蓝色')
  const other = (await b.get('list_common').execute({})).results[0]
  assert.equal((await a.get('update_common').execute({ id: other.id, note: '跨群改动' })).ok, false)
  assert.equal((await a.get('forget_common').execute({ id: other.id })).ok, false)
  assert.equal((await a.get('forget_common').execute({ 片段: '蓝色' })).ok, false)
  assert.equal((await a.get('remember_common').execute({ note: '不该新增', 取代: '蓝色' })).ok, false, '宿主不能把引擎失败变成 ok=true')
  assert.equal((await a.get('update_common').execute({ id: own.id, note: '小明喜欢绿色' })).ok, true)
  assert.equal((await a.get('recall_common').execute({ query: '绿色' })).results[0].id, own.id)

  const snapshot = readFileSync(memoryFile, 'utf8')
  for (const key of ['总开关', '试运行']) {
    const original = config[key]
    config[key] = key === '试运行'
    save()
    assert.equal((await a.get('remember_common').execute({ note: '不能新增' })).ok, false)
    assert.equal((await a.get('update_common').execute({ id: own.id, note: '不能修改' })).ok, false)
    assert.equal((await a.get('forget_common').execute({ id: own.id })).ok, false)
    config[key] = original
    save()
  }
  assert.equal(readFileSync(memoryFile, 'utf8'), snapshot)
  assert.equal((await a.get('forget_common').execute({ id: own.id })).删, 1)
  assert.equal((await a.get('list_common').execute({})).total, 1)
  assert.equal((await b.get('list_common').execute({})).results[0].说, '小明喜欢蓝色')
  assert.equal((await c.get('list_common').execute({})).results[0].说, '小明喜欢蓝色')
  console.log('记忆工具宿主：注册、当前聊天来源、跨群拒绝、真实失败返回和写入开关通过')
} finally {
  bridge?.dispose?.()
  globalThis.fetch = old.fetch
  globalThis.setTimeout = old.setTimeout
  globalThis.clearTimeout = old.clearTimeout
  if (old.home === undefined) delete process.env.DSH_HOME
  else process.env.DSH_HOME = old.home
  rmSync(home, { recursive: true, force: true })
}
