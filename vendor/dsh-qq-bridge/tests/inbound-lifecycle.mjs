import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const originalFetch = globalThis.fetch
const originalTimeout = globalThis.setTimeout
const originalClear = globalThis.clearTimeout
const originalHome = process.env.DSH_HOME
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise(setImmediate) }
const message = (id = 1, time = 9999999999, forward = false) => ({ user_id: 123, time, message_id: id,
  message: [{ type: forward ? 'forward' : 'text', data: forward ? { id: 'synthetic-forward' } : { text: 'synthetic' } }] })
const history = (messages = [message()]) => ({ status: 'ok', data: { messages } })
const forward = () => ({ status: 'ok', data: { messages: [{ sender: { nickname: 'synthetic' }, content: [{ type: 'text', data: { text: 'synthetic forward' } }] }] } })
const response = data => ({ json: async () => data })
let serial = 0
async function fixture() {
  const home = mkdtempSync(join(tmpdir(), 'qq-lifecycle-'))
  process.env.DSH_HOME = home
  // Main includes the watermark initialization fix; reload the actual host directly.
  const hostPath = resolve(process.env.QQ_TEST_HOST || 'lib/host.js')
  const host = await import(pathToFileURL(hostPath).href + '?lifecycle=' + ++serial)
  writeFileSync(join(home, 'qq-bridge-config.json'), JSON.stringify({ 总开关: true, 试运行: true, 收图: false, 合并窗口秒: 0,
    绑定: [{ 类型: '私聊', 号码: '123', 会话: 'session-X' }], NapCat: 'http://synthetic.invalid' }))
  const timers = new Map(), requests = [], instances = []
  globalThis.setTimeout = (fn, ms, ...args) => {
    if (ms < 5000) return originalTimeout(fn, ms, ...args)
    const id = {}; timers.set(id, { fn, ms }); return id
  }
  globalThis.clearTimeout = id => timers.delete(id) || originalClear(id)
  let fetchImpl = async () => response(history())
  globalThis.fetch = (...args) => { requests.push(args); return fetchImpl(...args) }
  const mount = () => {
    const calls = [], offs = []; let tick, follow = async () => {}, flush = async () => {}
    const agent = { session: { id: 'session-X' }, followup: m => { calls.push(m); return follow(m) } }
    host.apply({ effect(fn) { offs.push(fn()) }, on: () => () => {}, webServer: { register() {} },
      interval(fn) { tick = fn; return () => {} }, agents: { get: () => agent },
      sessions: { flush: () => flush() }, logger: { info() {} }, get() {} })
    const instance = { calls, tick: () => tick(), dispose: () => offs.forEach(fn => fn?.()), follow: fn => { follow = fn }, flush: fn => { flush = fn } }
    instances.push(instance); return instance
  }
  const f = { mount, requests, fetch: fn => { fetchImpl = fn }, deadlineCount: () => timers.size,
    deadlineMillis: () => [...timers.values()].map(timer => timer.ms),
    expire: () => [...timers.values()].forEach(timer => timer.fn()), state: () => JSON.parse(readFileSync(join(home, 'qq-bridge-state.json'), 'utf8')),
    save: state => writeFileSync(join(home, 'qq-bridge-state.json'), JSON.stringify(state)),
    close() { instances.forEach(i => i.dispose()); globalThis.setTimeout = originalTimeout; globalThis.clearTimeout = originalClear; globalThis.fetch = originalFetch; rmSync(home, { recursive: true, force: true }) } }
  return f
}
let failures = 0
async function check(label, run) {
  const f = await fixture()
  try { await run(f); console.log('PASS ' + label) }
  catch (error) { failures++; console.error('FAIL ' + label + ': ' + error.stack) }
  finally { f.close() }
}

await check('disposed accepted followup persists its ID and merges only its success into current disk state', async f => {
  const gate = deferred(), a = f.mount(); a.follow(() => gate.promise)
  const pending = a.tick(); await settle(); assert.equal(a.calls.length, 1); a.dispose()
  f.save({ 上次: { '私聊:123': 10000000001, '群:456': 10000000002 }, 已转: [50, 51] })
  gate.resolve(); await pending
  assert.deepEqual(f.state(), { 上次: { '私聊:123': 10000000001, '群:456': 10000000002 }, 已转: [50, 51, 1] })
})

await check('late success survives newer instance writes and reload does not redeliver', async f => {
  const gate = deferred(), old = f.mount(); old.follow(() => gate.promise)
  const pending = old.tick(); await settle(); old.dispose()
  const current = f.mount()
  f.fetch(async () => response(history([message(2, 10000000001)])))
  await current.tick(); assert.equal(current.calls.length, 1)
  gate.resolve(); await pending
  await current.tick() // A newer instance with an older in-memory Set must retain the late ID.
  assert.equal(f.state().上次['私聊:123'], 10000000001)
  assert.ok(f.state().已转.includes(1)); assert.ok(f.state().已转.includes(2))
  current.dispose()
  const reloaded = f.mount()
  f.fetch(async () => response(history([message(), message(2, 10000000001)])))
  await reloaded.tick(); assert.equal(reloaded.calls.length, 0)
})

for (const action of ['history', 'forward']) for (const phase of ['fetch', 'json']) {
  await check(`${action} ${phase} deadline releases lock, retries, and ignores late completion`, async f => {
    const gate = deferred(), a = f.mount(); let blocked = false
    f.fetch(async url => {
      if (action === 'forward' && !url.endsWith('/get_forward_msg')) return response(history([message(1, 9999999999, true)]))
      blocked = true
      return phase === 'fetch' ? gate.promise : { json: () => gate.promise }
    })
    const pending = a.tick(); await settle(); assert.equal(blocked, true); assert.equal(f.deadlineCount(), 1)
    assert.deepEqual(f.deadlineMillis(), [8000])
    const request = f.requests.at(-1)
    f.expire(); await pending
    assert.equal(request[1].signal.aborted, true); assert.equal(f.deadlineCount(), 0); assert.equal(a.calls.length, 0)
    f.fetch(async url => response(url.endsWith('/get_forward_msg') ? forward() : history([message(1, 9999999999, action === 'forward')])))
    await a.tick(); assert.equal(a.calls.length, 1)
    gate.resolve(phase === 'fetch' ? response(action === 'forward' ? forward() : history()) : action === 'forward' ? forward() : history())
    await settle(); assert.equal(a.calls.length, 1); assert.equal(f.deadlineCount(), 0)
  })
}

for (const action of ['history', 'forward']) {
  await check(`dispose interrupts pending ${action} JSON body without a ghost delivery`, async f => {
    const gate = deferred(), a = f.mount()
    f.fetch(async url => {
      if (action === 'forward' && !url.endsWith('/get_forward_msg')) return response(history([message(1, 9999999999, true)]))
      return { json: () => gate.promise }
    })
    const pending = a.tick(); await settle(); assert.equal(f.deadlineCount(), 1); a.dispose(); await pending
    assert.equal(a.calls.length, 0); assert.equal(f.deadlineCount(), 0)
    gate.resolve(action === 'forward' ? forward() : history()); await settle(); assert.equal(a.calls.length, 0)
  })
}

await check('accepted followup is recorded before a pending session flush and disposal', async f => {
  const gate = deferred(), a = f.mount(); a.flush(() => gate.promise)
  const pending = a.tick(); await settle(); assert.equal(a.calls.length, 1)
  assert.ok(f.state().已转.includes(1)); a.dispose()
  gate.resolve(); await pending; assert.ok(f.state().已转.includes(1))
})

await check('followup has no read deadline and remains single-flight until acceptance settles', async f => {
  const gate = deferred(), a = f.mount(); a.follow(() => gate.promise)
  const pending = a.tick(); await settle(); assert.equal(a.calls.length, 1); assert.equal(f.deadlineCount(), 0)
  f.expire(); assert.equal(a.tick(), pending); assert.equal(a.calls.length, 1)
  gate.resolve(); await pending; assert.ok(f.state().已转.includes(1))
})

if (originalHome === undefined) delete process.env.DSH_HOME
else process.env.DSH_HOME = originalHome
process.exitCode = failures ? 1 : 0
