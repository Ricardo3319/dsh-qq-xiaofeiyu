// 假宿主验证新增工具确实注册、使用当前配置、从绑定确定记忆作用域。
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const old = { home: process.env.DSH_HOME, fetch: globalThis.fetch,
  setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout }
const home = mkdtempSync(join(tmpdir(), 'qq-research-host-'))
process.env.DSH_HOME = home
const sid = 'session-research'
const config = { 总开关: true, 试运行: false, 允许联网: true, 合并窗口秒: 0, 收图: false,
  搜索地址: 'https://search.example.com', 网页最多字: 777,
  NapCat: 'http://synthetic.invalid', 绑定: [{ 类型: '私聊', 号码: '123', 会话: sid }] }
const save = () => writeFileSync(join(home, 'qq-bridge-config.json'), JSON.stringify(config))
save()
writeFileSync(join(home, 'qq-bridge-memory.json'), JSON.stringify({ version: 1, 条目: [
  { 说: '约好周五写文案', 类: '约定', 来源: '私聊', 哪: '123', 时: Date.now() },
  { 说: '另一人的文案', 类: '约定', 来源: '私聊', 哪: '999', 时: Date.now() },
] }))
globalThis.setTimeout = () => ({})
globalThis.clearTimeout = () => {}
const requests = []
globalThis.fetch = async (url) => {
  requests.push(String(url))
  if (String(url).startsWith(config.搜索地址)) return new Response(JSON.stringify({ results: [{ title: '标准', url: 'https://onebot.dev/', content: '标准说明' }] }))
  return { ok: true, json: async () => ({ status: 'ok', data: String(url).endsWith('get_login_info') ? { user_id: 10001 } : { messages: [] } }) }
}
let tick, bridge
const tools = new Map(), routes = new Map()
const agent = { session: { id: sid }, ctx: { tools: {
  register(tool) { tools.set(tool.name, tool); return () => tools.delete(tool.name) },
} }, followup() {} }
try {
  const host = await import('../lib/host.js')
  bridge = host.apply({
    effect(fn) { return fn() }, on: () => () => {},
    webServer: { register(route) { routes.set(route.path, route) } },
    interval(fn) { tick = fn; return () => {} }, agents: { get: () => agent },
    sessions: { flush: async () => {} }, attachments: { admitPromptContent: c => c },
    logger: { info() {} }, get() {},
  })
  await tick()
  for (const name of ['qq_web_search', 'qq_read_url', 'recall_common']) assert.ok(tools.has(name), name + ' 应挂到 QQ 会话')
  const found = await tools.get('qq_web_search').execute({ query: 'OneBot' })
  assert.equal(found.results[0].url, 'https://onebot.dev/')
  const remembered = await tools.get('recall_common').execute({ query: '文案' })
  assert.deepEqual(remembered.results.map(x => x.说), ['约好周五写文案'])
  const count = requests.length
  config.允许联网 = false
  save()
  assert.equal((await tools.get('qq_web_search').execute({ query: 'OneBot' })).ok, false)
  assert.equal(requests.length, count, '已有工具也必须读取最新开关')
  console.log('宿主接入：工具注册、配置归一化、动态开关和绑定作用域通过')
} finally {
  bridge?.dispose?.()
  globalThis.fetch = old.fetch
  globalThis.setTimeout = old.setTimeout
  globalThis.clearTimeout = old.clearTimeout
  if (old.home === undefined) delete process.env.DSH_HOME
  else process.env.DSH_HOME = old.home
  rmSync(home, { recursive: true, force: true })
}
