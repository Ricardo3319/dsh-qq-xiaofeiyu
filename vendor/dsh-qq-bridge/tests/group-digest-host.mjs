import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const old = { home: process.env.DSH_HOME, fetch: globalThis.fetch, now: Date.now,
  setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout }
const home = mkdtempSync(join(tmpdir(), 'qq-digest-host-'))
process.env.DSH_HOME = home
let now = 1800000000000, tick, failed = false, followups = 0
const messageTime = (now - 10000) / 1000
Date.now = () => now
const config = { 总开关: true, 试运行: false, 收图: false, NapCat: 'http://napcat.invalid',
  绑定: [
    { 类型: '群', 号码: '111', 会话: 'session-A', 只听点名: true },
    { 类型: '群', 号码: '222', 会话: 'session-B' },
    { 类型: '私聊', 号码: '333', 会话: 'session-C' },
    { 类型: '群', 号码: '444', 会话: 'session-shared' },
    { 类型: '群', 号码: '555', 会话: 'session-shared' },
  ] }
const save = () => writeFileSync(join(home, 'qq-bridge-config.json'), JSON.stringify(config))
save()
globalThis.setTimeout = () => ({})
globalThis.clearTimeout = () => {}
const requests = []
globalThis.fetch = async (url, options) => {
  requests.push(url)
  if (failed) throw Error('模拟网络失败')
  assert.ok(url.endsWith('_msg_history'), '摘要不能新增 QQ API 请求')
  const body = JSON.parse(options.body)
  const who = body.group_id || body.user_id
  return { json: async () => ({ status: 'ok', data: { messages: [{
    message_id: who, time: messageTime, user_id: 900,
    sender: { nickname: '群友' }, message: [{ type: 'text', data: { text: `聊天 ${who} 的讨论` } }],
  }] } }) }
}
const effects = [], toolsets = new Map(), agents = new Map()
for (const sid of ['session-A', 'session-B', 'session-C', 'session-shared']) {
  const tools = new Map()
  toolsets.set(sid, tools)
  agents.set(sid, { session: { id: sid }, ctx: { tools: {
    register(tool) { tools.set(tool.name, tool); return () => tools.delete(tool.name) },
  } }, followup() { followups++ } })
}
try {
  const host = await import('../lib/host.js')
  host.apply({ effect(fn) { effects.push(fn()) }, on: () => () => {},
    webServer: { register() {} }, interval(fn) { tick = fn; return () => {} },
    agents: { get: id => agents.get(id) }, sessions: { flush: async () => {} },
    attachments: { admitPromptContent: c => c }, logger: { info() {} }, get() {},
  })
  await tick()
  const a = toolsets.get('session-A').get('qq_group_digest')
  const b = toolsets.get('session-B').get('qq_group_digest')
  assert.equal(a.parameters.type, 'object')
  assert.ok(a.output)
  const beforeRead = requests.length
  const result = await a.execute({})
  assert.equal(result.ok, true)
  assert.equal(result.messages[0].text, '聊天 111 的讨论')
  assert.equal((await b.execute({})).messages[0].text, '聊天 222 的讨论')
  assert.equal((await a.execute({ group_id: '222' })).group_id, '111', '不能由模型指定跨群查询')
  assert.equal((await a.execute({ before_id: '222' })).ok, false)
  assert.equal((await toolsets.get('session-C').get('qq_group_digest').execute({})).ok, false)
  assert.equal((await toolsets.get('session-shared').get('qq_group_digest').execute({})).ok, false)
  assert.equal(requests.length, beforeRead, '执行摘要只读取已有缓存')
  assert.equal(followups, 0, '记录未点名的消息不应唤醒模型')
  assert.equal(readdirSync(home).some(x => /digest|摘要|memory/.test(x)), false, '缓存不写长期记忆或聊天文件')

  failed = true
  now += 60000
  await tick()
  const stale = await a.execute({})
  assert.equal(stale.last_polled_at, result.last_polled_at, '失败轮询不能伪装新记录')
  assert.equal(stale.messages.length, 1)
  config.绑定[0].开 = false
  save()
  assert.equal((await a.execute({})).ok, false)
  await tick()
  config.绑定[0].开 = true
  save()
  assert.equal((await a.execute({})).messages.length, 0, '停用后丢弃该群缓存')

  for (const key of ['总开关', '试运行']) {
    failed = false
    await tick()
    assert.equal((await a.execute({})).messages.length, 1)
    config[key] = key === '试运行'
    save()
    assert.equal((await a.execute({})).ok, false)
    await tick()
    config[key] = key !== '试运行'
    save()
    assert.equal((await a.execute({})).messages.length, 0, '关闭/试运行清空缓存且不重新收集')
  }
  effects.forEach(fn => fn?.())
  effects.length = 0
  assert.equal((await a.execute({})).ok, false, '停止后旧工具不能继续读缓存')
  console.log('群聊摘要宿主：注册、轮询复用、来源隔离、无额外请求/唤醒、失败时间及开关/停止通过')
} finally {
  effects.forEach(fn => fn?.())
  globalThis.fetch = old.fetch
  globalThis.setTimeout = old.setTimeout
  globalThis.clearTimeout = old.clearTimeout
  Date.now = old.now
  if (old.home === undefined) delete process.env.DSH_HOME
  else process.env.DSH_HOME = old.home
  rmSync(home, { recursive: true, force: true })
}
