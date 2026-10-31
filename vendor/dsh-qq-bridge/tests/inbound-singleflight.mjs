import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import assert from 'node:assert/strict'

// A new synthetic home per apply keeps each concurrency scenario independent.
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(setImmediate) }
let count = 0
async function scenario(label, run) {
  ++count
  const scenarioHome = mkdtempSync(join(tmpdir(), 'qq-singleflight-case-'))
  process.env.DSH_HOME = scenarioHome
  const host = await import(pathToFileURL(resolve(process.env.QQ_TEST_HOST || 'lib/host.js')).href + '?case=' + count)
  writeFileSync(join(scenarioHome, 'qq-bridge-config.json'), JSON.stringify({ 总开关: true, 试运行: true, 收图: true, 合并窗口秒: 0, 绑定: [{ 类型: '私聊', 号码: '123', 会话: 'session-X' }], NapCat: 'http://synthetic.invalid' }))
  const effects = [], calls = [], requests = []
  let tick, stopped = false, fetchImpl, followImpl = async () => {}, admitImpl = async (content) => content
  globalThis.fetch = (...args) => { requests.push(args); return fetchImpl(...args) }
  const agent = { session: { id: 'session-X' }, followup: (m) => { calls.push(m); return followImpl(m) } }
  host.apply({
    effect: (fn) => { const dispose = fn(); effects.push(dispose) },
    on: () => () => {}, webServer: { register() {} },
    interval: (fn) => { tick = fn; return () => { stopped = true } },
    attachments: { admitPromptContent: (content) => admitImpl(content) },
    agents: { get: () => agent }, sessions: { flush: async () => {} },
    logger: { info() {} }, get() {},
  })
  const message = { user_id: 123, time: 9999999999, message_id: count, message: [{ type: 'text', data: { text: 'synthetic' } }] }
  const response = (messages = [message]) => ({ json: async () => ({ status: 'ok', data: { messages } }) })
  const fixture = { tick: () => tick(), dispose: () => effects.forEach((f) => f?.()), calls, requests, response,
    attach: (fn) => { admitImpl = fn }, fetch: (fn) => { fetchImpl = fn }, follow: (fn) => { followImpl = fn }, stopped: () => stopped }
  try { await run(fixture); console.log('PASS ' + label) }
  finally { fixture.dispose() }
}
let failures = 0
for (const [label, run] of [
  ['slow history fetch is single-flight and delivered once', async (f) => {
    const gate = deferred(); f.fetch(() => gate.promise)
    f.tick(); f.tick(); await settle()
    const concurrentRequests = f.requests.length
    gate.resolve(f.response()); await settle()
    const initialDeliveries = f.calls.length
    f.tick(); await settle()
    assert.equal(concurrentRequests, 1, `overlapping history requests: ${concurrentRequests}; deliveries: ${initialDeliveries}`)
    assert.equal(f.calls.length, 1)
  }],
  ['pending followup is single-flight and replay stays deduplicated', async (f) => {
    const gate = deferred(); f.fetch(async () => f.response()); f.follow(() => gate.promise)
    f.tick(); await settle(); f.tick(); await settle()
    const concurrentDeliveries = f.calls.length
    gate.resolve(); await settle(); f.tick(); await settle()
    assert.equal(concurrentDeliveries, 1, `overlapping followups: ${concurrentDeliveries}`)
    assert.equal(f.calls.length, 1)
  }],
  ['rejected followup releases lock and can retry', async (f) => {
    f.fetch(async () => f.response()); f.follow(async () => { throw Error('synthetic rejection') })
    f.tick(); await settle(); f.follow(async () => {}); f.tick(); await settle()
    assert.equal(f.calls.length, 2)
    f.tick(); await settle(); assert.equal(f.calls.length, 2)
  }],
  ['fetch failure releases lock', async (f) => {
    f.fetch(async () => { throw Error('synthetic network failure') }); f.tick(); await settle()
    f.fetch(async () => f.response()); f.tick(); await settle(); assert.equal(f.calls.length, 1)
  }],
  ['dispose aborts history request and ignores late response', async (f) => {
    const gate = deferred(); f.fetch(() => gate.promise); f.tick(); await settle(); f.dispose()
    assert.equal(f.stopped(), true)
    assert.equal(f.requests[0][1].signal?.aborted, true)
    gate.resolve(f.response()); await settle(); f.tick(); await settle(); assert.equal(f.calls.length, 0)
  }],
  ['dispose during attachment admission prevents followup', async (f) => {
    const gate = deferred(); let admissions = 0
    f.attach(() => { admissions++; return gate.promise })
    f.fetch(async () => f.response([{ user_id: 123, time: 9999999999, message_id: 8000,
      message: [{ type: 'text', data: { text: 'synthetic picture' } }, { type: 'image', data: { file: 'base64://iVBORw0KGgo=' } }] }]))
    f.tick(); await settle(); assert.equal(admissions, 1)
    f.dispose(); gate.resolve([{ type: 'text', text: 'synthetic' }]); await settle()
    assert.equal(f.calls.length, 0)
  }],
  ['dispose during followup stops later messages', async (f) => {
    const gate = deferred(); let first = true
    f.fetch(async () => { const a = f.response(); const j = await a.json(); j.data.messages.push({ ...j.data.messages[0], message_id: 10000 }); return { json: async () => j } })
    f.follow(() => first ? (first = false, gate.promise) : Promise.resolve())
    f.tick(); await settle(); f.dispose(); gate.resolve(); await settle(); assert.equal(f.calls.length, 1)
  }],
]) { try { await scenario(label, run) } catch (error) { failures++; console.error('FAIL ' + label + ': ' + error.message) } }
process.exitCode = failures ? 1 : 0
