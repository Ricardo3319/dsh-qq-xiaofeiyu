import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const old = { home: process.env.DSH_HOME, fetch, now: Date.now, setTimeout, clearTimeout }
const home = mkdtempSync(join(tmpdir(), 'qq-interaction-'))
process.env.DSH_HOME = home
const file = join(home, 'qq-bridge-config.json'), state = join(home, 'qq-bridge-state.json')
let now = Date.parse('2026-11-06T02:00:00+08:00'), failSend = false, sendGate = null, serial = 0
Date.now = () => now
globalThis.setTimeout = () => ({})
globalThis.clearTimeout = () => {}
const policy = { quiet_start: '01:00', quiet_end: '08:00', timezone: 'Asia/Shanghai', min_interval_minutes: 20, weekday_interval_minutes: 60 }
let config = { 总开关: true, 试运行: false, 转私聊: true, 转群: true, 收图: false, 发图: false, 发文件: false,
  合并窗口秒: 0, 回复冷却秒: 0, 每分钟最多条: 100, 群里听所有人: true, 来源头: false,
  NapCat: 'http://napcat.invalid', 绑定: [
    { 类型: '私聊', 号码: '123', 会话: 'session-P', 互动: { ...policy } },
    { 类型: '群', 号码: '456', 会话: 'session-G', 互动: { ...policy } },
    { 类型: '群', 号码: '789', 会话: 'session-H' },
  ] }
const save = () => writeFileSync(file, JSON.stringify(config))
save()
writeFileSync(state, JSON.stringify({ 上次: { '群:456': now / 1000 - 60, '私聊:123': now / 1000 - 60 }, 已转: [] }))
const messages = new Map(), sent = [], effects = []
globalThis.fetch = async (url, opt) => {
  const body = JSON.parse(opt.body || '{}')
  let data = {}
  if (url.endsWith('/get_login_info')) data = { user_id: 10001 }
  else if (url.endsWith('_msg_history')) data = { messages: messages.get(String(body.group_id || body.user_id)) || [] }
  else if (url.includes('/send_')) {
    sent.push(body)
    if (sendGate) await sendGate
    return { json: async () => ({ status: failSend ? 'failed' : 'ok', retcode: failSend ? 1 : 0, data: { message_id: 90000 + sent.length } }) }
  }
  return { json: async () => ({ status: 'ok', retcode: 0, data }) }
}
const settle = async () => { for (let i = 0; i < 25; i++) await new Promise(setImmediate) }
const row = (id, pointed = false, user = 123) => ({ message_id: id, user_id: user, time: now / 1000,
  sender: { nickname: '测试用户' }, message: [...(pointed ? [{ type: 'at', data: { qq: '10001' } }] : []), { type: 'text', data: { text: '今天讨论一下' } }] })
let tick, bridge, tools, incoming, routes
try {
  const host = await import('../lib/host.js')
  const mount = () => {
    tools = new Map(); incoming = []; routes = new Map()
    const agents = new Map(['P', 'G', 'H'].map(k => {
      const ts = new Map(); tools.set(k, ts)
      return ['session-' + k, { session: { id: 'session-' + k }, ctx: { tools: { register(t) { ts.set(t.name, t); return () => {} } } },
        followup(m) { incoming.push({ k, m }) } }]
    }))
    bridge = host.apply({ effect(fn) { effects.push(fn()) }, on: () => () => {},
      webServer: { register(o) { routes.set(o.path, o.handler) } }, interval(fn) { tick = fn; return () => {} },
      agents: { get: id => agents.get(id) }, sessions: { flush: async () => {} }, attachments: { admitPromptContent: c => c },
      logger: { info() {} }, get: name => name === 'connection' ? { requestRejection: () => undefined } : undefined })
  }
  const finish = async (k, source = 'qq') => {
    const s = { id: 'session-' + k }, turn = ++serial
    bridge.收到事件(s, { type: 'turn/start', data: { turn } })
    bridge.收到事件(s, { type: 'user/message', data: { source: { kind: source } } })
    bridge.收到事件(s, { type: 'assistant/message', data: { turn, message: { role: 'assistant', content: [{ type: 'text', text: '收到，这是一条回复。' }] } } })
    bridge.收到事件(s, { type: 'turn/end', data: { turn, reason: { kind: 'completed' } } })
    await settle()
  }
  mount()
  messages.set('456', [row(1)])
  await tick()
  assert.equal(incoming.length, 0, '免打扰时闲聊不进入模型')
  assert.ok(JSON.parse(readFileSync(state)).已转.includes(1))
  messages.set('456', [row(2, true)])
  await tick()
  assert.equal(incoming.length, 1, '@ 仍正常进入')
  const tool = tools.get('G').get('qq_interaction_settings')
  assert.equal((await tool.execute({})).settings.timezone, 'Asia/Shanghai')
  assert.equal((await tool.execute({ min_interval_minutes: 25 })).ok, true)
  assert.equal(statSync(file).mode & 0o777, 0o600, '保存后的配置不能对其他用户开放读取')
  config = JSON.parse(readFileSync(file))
  assert.equal(config.绑定[0].互动.min_interval_minutes, 20, '只能改当前聊天')
  const snapshot = readFileSync(file, 'utf8')
  assert.equal((await tool.execute({ quiet_start: '25:00' })).ok, false)
  mkdirSync(file + '.tmp')
  assert.equal((await tool.execute({ min_interval_minutes: 30 })).ok, false)
  rmSync(file + '.tmp', { recursive: true })
  assert.equal(readFileSync(file, 'utf8'), snapshot, '保存失败不能破坏旧配置')
  let response
  await routes.get('/dsh-qq-bridge/save')([JSON.stringify({ 绑定: config.绑定.map(b => ({ ...b, 互动: { ...policy, timezone: 'No/SuchZone' } })) })], { end: s => { response = JSON.parse(s) } })
  assert.equal(response.ok, false)
  assert.equal(readFileSync(file, 'utf8'), snapshot)
  await finish('G')
  assert.equal(sent.length, 1, '免打扰不拦明确回复')
  await finish('G', 'speak-up')
  assert.equal(sent.length, 1, '自动搭话不能借用 QQ 唤醒尾巴')
  messages.set('123', [row(20)])
  messages.set('456', [row(3, true, 999)])
  await tick()
  assert.equal((await tool.execute({ quiet_start: '00:00' })).ok, false, '其他群成员不能改主人设置')
  const privateTool = tools.get('P').get('qq_interaction_settings')
  assert.equal((await privateTool.execute({ min_interval_minutes: 20 })).ok, true)
  await finish('P')
  assert.equal(sent.at(-1).user_id, 123, '私聊来信在夜间仍回复')
  await finish('G')

  now = Date.parse('2026-11-06T08:00:00+08:00')
  messages.set('456', [row(1), row(4)])
  messages.set('123', [])
  const before = incoming.length
  await tick()
  assert.equal(incoming.length, before + 1, '恢复时不重放被略过的消息')
  await finish('G')
  const last = JSON.parse(readFileSync(state)).主动上次['群:456']
  assert.equal(last, now)
  messages.set('456', [row(5)])
  await tick()
  assert.equal(incoming.length, before + 1, '工作日冷却期间不接闲聊')
  messages.set('456', [row(6, true)])
  await tick()
  assert.equal(incoming.length, before + 2)
  await finish('G')
  assert.equal(JSON.parse(readFileSync(state)).主动上次['群:456'], last, '明确回复不重新计算主动间隔')
  const count = sent.length
  await finish('G', 'speak-up')
  assert.equal(sent.length, count)
  await bridge.发到QQ(config, '其他群不受影响', [], 'session-H', '', true)
  assert.equal(sent.at(-1).group_id, 789)

  effects.splice(0).forEach(fn => fn?.())
  mount()
  const afterRestart = await bridge.发到QQ(config, '重启不能重置冷却', [], 'session-G', '', true)
  assert.equal(afterRestart.length, 0)
  now += 60 * 60000
  failSend = true
  await bridge.发到QQ(config, '失败不占冷却', [], 'session-G', '', true)
  assert.equal(JSON.parse(readFileSync(state)).主动上次['群:456'], last)
  failSend = false
  let release
  sendGate = new Promise(r => { release = r })
  const first = bridge.发到QQ(config, '正在发送的第一条', [], 'session-G', '', true)
  await settle()
  assert.equal((await bridge.发到QQ(config, '不能并发插话', [], 'session-G', '', true)).length, 0)
  release(); await first; sendGate = null
  assert.equal(JSON.parse(readFileSync(state)).主动上次['群:456'], now)
  config.绑定[2] = { ...config.绑定[2], 会话: 'session-G', 互动: { ...policy } }
  save()
  now = Date.parse('2026-11-07T02:00:00+08:00')
  messages.set('456', [row(7, true)])
  await tick()
  const beforeShared = sent.length
  await finish('G')
  assert.deepEqual(sent.slice(beforeShared).map(x => x.group_id), [456], '本群点名不能让同会话的另一个群绕过免打扰')
  console.log('互动宿主：入站略过/不补发、明确呼叫/私聊放行、自动来源、隔离、设置权限/落盘、重启冷却、发送失败与并发通过')
} finally {
  effects.forEach(fn => fn?.())
  globalThis.fetch = old.fetch; globalThis.setTimeout = old.setTimeout; globalThis.clearTimeout = old.clearTimeout; Date.now = old.now
  if (old.home === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = old.home
  rmSync(home, { recursive: true, force: true })
}
