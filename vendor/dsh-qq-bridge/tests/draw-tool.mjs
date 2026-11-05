import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync, readdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

// qq_draw 的端到端（假宿主 + 假 fetch）：确认工具能挂上、会调生图接口、
// 只把图交给 NapCat，发完把临时文件删掉。
const originals = { fetch: globalThis.fetch, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout, now: Date.now, home: process.env.DSH_HOME }
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(setImmediate) }
const ok = (data) => ({ ok: true, status: 200, json: async () => ({ status: 'ok', data }), text: async () => '' })
const home = mkdtempSync(join(tmpdir(), 'qq-draw-'))
const 会话 = 'session-X'
const 生图地址 = 'http://synthetic.invalid/v1/images/generations'
const jpeg = Buffer.alloc(64)
jpeg[0] = 0xff; jpeg[1] = 0xd8; jpeg[2] = 0xff

let now = 2000000000000
Date.now = () => now
process.env.DSH_HOME = home
writeFileSync(join(home, 'qq-bridge-config.json'), JSON.stringify({
  总开关: true, 试运行: false, 允许生图: true, 生图地址, 生图模型: 'grok/grok-imagine-image',
  生图冷却秒: 0, 合并窗口秒: 0, 收图: false, NapCat: 'http://synthetic.invalid',
  绑定: [{ 类型: '私聊', 号码: '123', 会话 }],
}))
writeFileSync(join(home, 'qq-bridge-state.json'), JSON.stringify({ 上次: { '私聊:123': now / 1000 - 100 }, 已转: [] }))

const timers = new Map()
globalThis.setTimeout = (fn, ms) => { const t = { fn, ms }; timers.set(t, t); return t }
globalThis.clearTimeout = (t) => timers.delete(t)
const requests = []
globalThis.fetch = async (url, init = {}) => {
  const u = String(url)
  requests.push({ url: u, body: init.body })
  if (u.endsWith('/get_login_info')) return ok({ user_id: 10001 })
  if (u.includes('_msg_history')) return ok({ messages: [{ user_id: 123, message_id: 1, time: now / 1000 - 2, message: [{ type: 'text', data: { text: '画只猫' } }] }] })
  if (u === 生图地址) return { ok: true, status: 200, json: async () => ({ data: [{ b64_json: jpeg.toString('base64') }] }), text: async () => '' }
  if (u.includes('send_private_msg')) return { ok: true, status: 200, json: async () => ({ status: 'ok', retcode: 0, data: { message_id: 42 } }), text: async () => '' }
  return ok({})
}

const host = await import(pathToFileURL(resolve('lib/host.js')).href + '?draw=' + Date.now())
const calls = [], tools = []
let tick
const agent = {
  session: { id: 会话 },
  followup: (m) => { calls.push(m); return Promise.resolve() },
  ctx: { tools: { register(tool) { tools.push(tool); return () => {} } } },
}
const bridge = host.apply({
  effect(fn) { return fn() },
  on: () => () => {},
  webServer: { register() {} },
  interval(fn) { tick = fn; return () => {} },
  agents: { get: () => agent },
  attachments: { admitPromptContent: (c) => c },
  sessions: { flush: async () => {} },
  logger: { info: () => {} },
  get() {},
})

try {
  await tick(); await settle()
  assert.equal(calls.length, 1, '消息应该先被转进会话，生图才有「这一轮」的锚点')
  const draw = tools.find((t) => t.name === 'qq_draw')
  assert.ok(draw, 'qq_draw 应该挂上')
  const r = await draw.execute({ prompt: '一只橘猫戴草帽，水彩' })
  assert.match(r.说, /画好/)
  const gen = requests.find((x) => x.url === 生图地址)
  assert.ok(gen, '应该调生图接口')
  assert.deepEqual(JSON.parse(gen.body), { model: 'grok/grok-imagine-image', prompt: '一只橘猫戴草帽，水彩', n: 1 })
  assert.ok(requests.some((x) => x.url.includes('send_private_msg')), '图应该发给 NapCat')
  const out = join(home, 'qq-draw', 'out')
  assert.equal(existsSync(out) ? readdirSync(out).length : 0, 0, '发完应该删掉临时图')
  console.log('qq_draw 端到端：过')
} finally {
  try { bridge && bridge.dispose && bridge.dispose() } catch (e) {}
  globalThis.fetch = originals.fetch
  globalThis.setTimeout = originals.setTimeout
  globalThis.clearTimeout = originals.clearTimeout
  Date.now = originals.now
  if (originals.home === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = originals.home
  rmSync(home, { recursive: true, force: true })
}