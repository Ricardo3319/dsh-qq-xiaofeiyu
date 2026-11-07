import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, writeFileSync, mkdirSync, rmSync, statSync, existsSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const old = { home: process.env.DSH_HOME, fetch, now: Date.now, setTimeout, clearTimeout }
const home = mkdtempSync(join(tmpdir(), 'qq-preferences-'))
process.env.DSH_HOME = home
const file = join(home, 'qq-bridge-config.json')
let now = Date.parse('2026-11-07T10:00:00+08:00'), serial = 0
Date.now = () => now
globalThis.setTimeout = () => ({})
globalThis.clearTimeout = () => {}
let config = { 总开关: true, 试运行: false, 转私聊: true, 转群: true, 收图: false, 发图: false, 发文件: false,
  人设开: false, 允许发语音: true, 允许唱歌: true, 主动语音概率: 100, 语音冷却秒: 0, 主动语音冷却秒: 0,
  合并窗口秒: 0, 回复冷却秒: 0, 每分钟最多条: 100, 群里听所有人: true, 来源头: false,
  NapCat: 'http://napcat.invalid', 绑定: [
    { 类型: '私聊', 号码: '123', 会话: 'session-P' },
    { 类型: '群', 号码: '456', 会话: 'session-G' },
    { 类型: '群', 号码: '789', 会话: 'session-H' },
  ] }
const save = () => writeFileSync(file, JSON.stringify(config))
const reload = () => { config = JSON.parse(readFileSync(file)) }
save()
writeFileSync(join(home, 'qq-bridge-state.json'), JSON.stringify({ 上次: Object.fromEntries(['私聊:123', '群:456', '群:789'].map(k => [k, now / 1000 - 60])), 已转: [] }))
const messages = new Map(), sent = [], effects = [], tools = new Map(), incoming = [], routes = new Map(), agents = new Map(), prompts = new Map()
let assemblyGate = null
const makeAgent = k => {
  const ts = new Map(), sections = new Map([['original-persona', { name: 'original-persona', text: '原有性格保持原样' }]])
  prompts.set(k, sections); tools.set(k, ts)
  const sp = {
    getSectionOrder: () => 100,
    section(s) { sections.set(s.name, s); return () => { if (sections.get(s.name) === s) sections.delete(s.name) } },
    async assemble() { if (assemblyGate) await assemblyGate; return { sections: [...sections.values()] } },
  }
  const agent = { session: { id: 'session-' + k }, ctx: { get: name => name === 'systemPrompt' ? sp : undefined,
    tools: { register(t) { ts.set(t.name, t); return () => {} } } }, followup(m) { incoming.push({ k, m }) } }
  agents.set('session-' + k, agent)
}
for (const k of ['P', 'G', 'H']) makeAgent(k)
globalThis.fetch = async (url, opt) => {
  const body = JSON.parse(opt.body || '{}')
  let data = {}
  if (url.endsWith('/get_login_info')) data = { user_id: 10001 }
  else if (url.endsWith('_msg_history')) data = { messages: messages.get(String(body.group_id || body.user_id)) || [] }
  else if (url.includes('/send_')) { sent.push(body); data = { message_id: 90000 + sent.length } }
  return { json: async () => ({ status: 'ok', retcode: 0, data }) }
}
const settle = async () => { for (let i = 0; i < 25; i++) await new Promise(setImmediate) }
const tool = (k, name = 'qq_chat_preferences') => tools.get(k).get(name)
const text = k => [...prompts.get(k).values()].map(s => s.text).join('\n')
const defaults = { nickname: '', reply_length: 'default', voice: 'default' }
let tick, bridge
const receive = async (number, user = 123) => {
  now += 1000
  messages.set(number, [{ message_id: ++serial, user_id: user, time: now / 1000,
    sender: { nickname: '测试用户' }, message: [{ type: 'at', data: { qq: '10001' } }, { type: 'text', data: { text: '请调整偏好' } }] }])
  await tick(); await settle()
}
try {
  const host = await import('../lib/host.js')
  bridge = host.apply({ effect(fn) { effects.push(fn()) }, on: () => () => {},
    webServer: { register(o) { routes.set(o.path, o.handler) } }, interval(fn) { tick = fn; return () => {} },
    agents: { get: id => agents.get(id) }, sessions: { flush: async () => {} }, attachments: { admitPromptContent: c => c },
    logger: { info() {} }, get: name => name === 'connection' ? { requestRejection: () => undefined } : undefined })
  await tick(); await settle()
  const initial = readFileSync(file, 'utf8')
  assert.deepEqual((await tool('P').execute({})).preferences, defaults)
  assert.equal(readFileSync(file, 'utf8'), initial, '查询不能写配置')
  assert.equal((await tool('P').execute({ nickname: '阿云' })).ok, false, '无 QQ 发起者时不得修改')
  await receive('123'); await receive('456')
  assert.equal((await tool('P').execute({ nickname: '阿云', reply_length: 'short', voice: 'off' })).prompt_status, 'applied')
  assert.equal(statSync(file).mode & 0o777, 0o600)
  assert.match(text('P'), /阿云/)
  assert.match(text('P'), /原有性格保持原样/)
  assert.doesNotMatch(text('G'), /阿云/)
  assert.doesNotMatch(JSON.stringify(incoming), /当前 QQ 聊天的表达偏好/, '偏好不能堆进用户消息历史')
  assert.equal((await tool('P', 'qq_voice').execute({ text: '测试' })).ok, false)
  assert.equal((await tool('P', 'qq_sing').execute({ text: '测试' })).ok, false)
  assert.equal(sent.length, 0)
  assert.equal((await tool('G').execute({ reply_length: 'detailed', voice: 'off' })).ok, true)
  assert.match(text('G'), /具体例子/)
  assert.equal((await tool('G').execute({ nickname: '全群同名' })).ok, false)
  const snapshot = readFileSync(file, 'utf8')
  mkdirSync(file + '.tmp')
  assert.equal((await tool('G').execute({ reply_length: 'short' })).ok, false)
  rmSync(file + '.tmp', { recursive: true })
  assert.equal(readFileSync(file, 'utf8'), snapshot)
  assert.match(text('G'), /具体例子/, '保存失败不能替换已生效提示')
  reload()
  let response
  await routes.get('/dsh-qq-bridge/save')([JSON.stringify({ 绑定: config.绑定.map(b => ({ ...b, 偏好: { voice: 'invalid' } })) })], { end: s => { response = JSON.parse(s) } })
  assert.equal(response.ok, false)
  assert.equal(readFileSync(file, 'utf8'), snapshot)
  await receive('456', 999)
  assert.equal((await tool('G').execute({ voice: 'default' })).ok, false, '普通群成员不能修改全群偏好')
  assert.equal((await tool('G').execute({})).ok, true)
  config.试运行 = true; save()
  assert.equal((await tool('P').execute({ voice: 'default' })).ok, false)
  config.试运行 = false; save()

  // 语音在合成中被关闭：真实子进程只产临时假音频，所有 QQ 请求仍为 mock。
  const script = join(home, 'tts.mjs'), hold = join(home, 'hold'), started = join(home, 'started')
  writeFileSync(script, `import {writeFileSync,existsSync} from 'node:fs';
process.stdin.resume(); process.stdin.on('end', async()=>{
writeFileSync(process.argv[3], 'started'); const deadline=Date.now()+4000;
while(existsSync(process.argv[4])) { if(Date.now()>deadline) process.exit(23); await new Promise(r=>setTimeout(r,10)); }
writeFileSync(process.argv[2], 'fake-audio'); });`)
  reload(); config.语音合成命令 = `${process.execPath} ${script} {out} ${started} ${hold}`; save()
  assert.equal((await tool('P').execute({ voice: 'default' })).ok, true)
  writeFileSync(hold, 'wait')
  const pending = tool('P', 'qq_voice').execute({ text: '合成途中关闭' })
  for (let i = 0; i < 200 && !existsSync(started); i++) await new Promise(r => old.setTimeout(r, 10))
  assert.ok(existsSync(started), '假合成器应已启动')
  assert.equal((await tool('P').execute({ voice: 'off' })).ok, true)
  rmSync(hold)
  assert.equal((await pending).ok, false)
  assert.equal(sent.length, 0, '合成完不能绕过新的关闭设置')
  assert.deepEqual(readdirSync(join(home, 'audio')), [], '被取消的音频应清理')
  await bridge.发到QQ(JSON.parse(readFileSync(file)), '主动语音也要关闭。', [], 'session-P', '', true)
  assert.ok(sent.length > 0)
  assert.equal(sent.flatMap(s => s.message).filter(s => s.type === 'record').length, 0)

  // 替换 agent 后补挂，恢复默认后撤段。
  const oldSections = prompts.get('P')
  // 本段验证提示服务替换；保留已注册工具句柄，不假设宿主会重建工具注册表。
  const privatePreferences = tool('P')
  makeAgent('P'); await tick(); await settle()
  assert.match(text('P'), /阿云/)
  assert.equal(oldSections.size, 1)
  assert.equal((await privatePreferences.execute(defaults)).ok, true)
  assert.equal(prompts.get('P').size, 1)

  // 共享会话不混称呼，但语音仍须找到本轮精确目标，不能取第一个群。
  reload(); config.绑定[2].会话 = 'session-G'; save()
  await receive('789')
  assert.equal((await tool('G').execute({ reply_length: 'short' })).prompt_status, 'shared_session')
  assert.equal(prompts.get('G').size, 1)
  const voice = await tool('G', 'qq_voice').execute({ text: '仅发到第二个群' })
  assert.equal(voice.说, '语音发出来了。')
  assert.equal(sent.at(-1).group_id, 789)
  await receive('456')
  assert.equal((await tool('G', 'qq_voice').execute({ text: '第一个群仍关闭' })).ok, false)
  reload()
  assert.equal(config.绑定[1].偏好.voice, 'off')
  assert.equal(config.绑定[2].偏好.voice, 'default')

  // 共用会话里主动语音也要跟随这一轮真正回应的聊天，不能固定群优先。
  reload(); config.绑定[0] = { ...config.绑定[0], 会话: 'session-G' }; save()
  await receive('123')
  const tailTurn = ++serial, tailSession = { id: 'session-G' }
  bridge.收到事件(tailSession, { type: 'turn/start', data: { turn: tailTurn } })
  bridge.收到事件(tailSession, { type: 'user/message', data: { source: { kind: 'qq' } } })
  bridge.收到事件(tailSession, { type: 'assistant/message', data: { turn: tailTurn, message: { role: 'assistant', content: [{ type: 'text', text: '短语音回复' }] } } })
  bridge.收到事件(tailSession, { type: 'turn/end', data: { turn: tailTurn, reason: { kind: 'completed' } } })
  const isRecord = x => Array.isArray(x.message) && x.message.some(m => m.type === 'record')
  const recordBefore = sent.filter(isRecord).length
  for (let i = 0; i < 400 && sent.filter(isRecord).length === recordBefore; i++) await new Promise(r => old.setTimeout(r, 10))
  const records = sent.filter(isRecord).slice(recordBefore)
  assert.equal(records.length, 1, '这一轮应主动念一条语音')
  assert.equal(records[0].user_id, 123, '私聊触发的主动语音不能念到群里')

  // 卸载发生在异步装配期间，完成后不得复活提示段。
  let release
  assemblyGate = new Promise(r => { release = r })
  const changing = privatePreferences.execute({ nickname: '新称呼' })
  await settle()
  effects.splice(0).forEach(fn => fn?.())
  release(); await changing; assemblyGate = null; await settle()
  assert.equal(prompts.get('P').size, 1)
  console.log('聊天偏好宿主：作用域/权限/原子保存、提示补挂/撤销、语音与唱歌拦截、合成中关闭、主动语音、共享会话精确目标通过')
} finally {
  effects.forEach(fn => fn?.())
  globalThis.fetch = old.fetch; globalThis.setTimeout = old.setTimeout; globalThis.clearTimeout = old.clearTimeout; Date.now = old.now
  if (old.home === undefined) delete process.env.DSH_HOME; else process.env.DSH_HOME = old.home
  rmSync(home, { recursive: true, force: true })
}
