import assert from 'node:assert/strict'
import { 做联网工具 } from '../lib/联网.js'

const original = { fetch: globalThis.fetch, now: Date.now }
let now = 2000000000000, status = 200, content = '', calls = []
Date.now = () => now
globalThis.fetch = async (endpoint, init) => {
  calls.push({ endpoint: String(endpoint), ...init })
  return new Response(JSON.stringify({ code: status, data: { title: '文章', content } }), { status })
}
const config = { 总开关: true, 试运行: false, 允许联网: true,
  阅读地址: 'https://reader.example.com', 联网超时秒: 5, 网页最多字: 500 }
const reader = () => 做联网工具(() => config)[1]
const url = 'https://example.com/article'
try {
  // 连读能恢复完整正文，emoji 不被切断；续读只用一次网络请求。
  content = '甲'.repeat(499) + '😀' + '乙'.repeat(700)
  const read = reader()
  const first = await read.execute({ url })
  assert.equal(first.next_start, 499)
  assert.equal(first.cached, false)
  assert.equal(first.total_chars, content.length)
  let page = first, combined = first.content
  while (page.next_start !== null) {
    const start = page.next_start
    page = await read.execute({ url, start })
    assert.equal(page.start, start)
    assert.equal(page.cached, true)
    assert.equal(page.content.isWellFormed(), true)
    assert.equal(page.fetched_at, first.fetched_at)
    combined += page.content
  }
  assert.equal(page.truncated, false)
  assert.equal(combined, content, '续读不能漏字、重字或损坏 emoji')
  assert.equal(calls.length, 1)
  for (const start of [-1, 0.5, '500', Infinity, content.length]) {
    assert.equal((await read.execute({ url, start })).ok, false)
  }
  assert.equal(calls.length, 1, '错误游标不应额外抓取缓存中的页面')

  // 即使缓存有内容，关联网、关总开关和试运行都要阻止工具使用。
  for (const key of ['允许联网', '总开关', '试运行']) {
    const old = config[key]
    config[key] = key === '试运行'
    assert.equal((await read.execute({ url })).ok, false)
    config[key] = old
  }
  assert.equal(calls.length, 1)

  // 要最新资料时同时跳过本地缓存和 Reader 缓存。
  content = '新的公开资料'
  now += 1000
  const fresh = await read.execute({ url, refresh: true })
  assert.equal(fresh.content, content)
  assert.equal(fresh.cached, false)
  assert.notEqual(fresh.fetched_at, first.fetched_at)
  assert.equal(calls.at(-1).headers['x-no-cache'], 'true')
  assert.equal(calls.length, 2)
  status = 503
  assert.equal((await read.execute({ url, refresh: true })).ok, false)
  assert.equal((await read.execute({ url })).ok, false, '刷新失败后不能把旧页面当新结果')
  status = 200
  await read.execute({ url })
  assert.equal(calls.length, 5)

  // 缓存时间从抓取完成算起，访问命中不延长有效期。
  now += 9 * 60 * 1000
  assert.equal((await read.execute({ url })).cached, true)
  now += 60 * 1000
  content = '十分钟后的资料'
  const expired = await read.execute({ url })
  assert.equal(expired.cached, false)
  assert.equal(expired.content, content)
  assert.equal(calls.length, 6)

  // 缓存不能跨会话/Reader 服务混用；修改字数上限即时生效。
  await reader().execute({ url })
  assert.equal(calls.length, 7, '另一个会话应独立获取网页')
  config.阅读地址 = 'https://another-reader.example.com'
  content = '新'.repeat(1600)
  assert.equal((await read.execute({ url })).cached, false)
  assert.equal(calls.length, 8)
  config.网页最多字 = 700
  const resized = await read.execute({ url, start: 500 })
  assert.equal(resized.content.length, 700)
  assert.equal(resized.next_start, 1200)
  assert.equal(calls.length, 8)

  // 每会话最多留八页；访问过的页面不会先于更久没用的页面被淘汰。
  const lru = reader()
  calls = []
  for (let i = 0; i < 8; i++) await lru.execute({ url: `https://example.com/${i}` })
  assert.equal((await lru.execute({ url: 'https://example.com/0' })).cached, true)
  await lru.execute({ url: 'https://example.com/8' })
  assert.equal((await lru.execute({ url: 'https://example.com/0' })).cached, true)
  assert.equal((await lru.execute({ url: 'https://example.com/1' })).cached, false)
  assert.equal(calls.length, 10)
  console.log('长文体验：续读完整性、emoji、缓存时效、刷新失败、会话隔离、配置更新和容量淘汰通过')
} finally {
  globalThis.fetch = original.fetch
  Date.now = original.now
}
