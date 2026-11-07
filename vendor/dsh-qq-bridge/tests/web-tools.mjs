import assert from 'node:assert/strict'
import { 做联网工具 } from '../lib/联网.js'

const original = globalThis.fetch
const config = { 总开关: true, 试运行: false, 允许联网: true,
  搜索地址: 'https://search.example.com/base/', 阅读地址: 'https://reader.example.com',
  联网超时秒: 5, 网页最多字: 500 }
const [search, read] = 做联网工具(() => config)
const requests = []
let payload
let status = 200
globalThis.fetch = async (url, init) => {
  requests.push({ url: String(url), ...init })
  return new Response(JSON.stringify(payload), { status })
}
try {
  for (const key of ['试运行', '总开关', '允许联网']) {
    const old = config[key]
    config[key] = key === '试运行'
    assert.equal((await search.execute({ query: 'NapCat' })).ok, false)
    assert.equal((await read.execute({ url: 'https://example.com' })).ok, false)
    config[key] = old
  }
  assert.equal(requests.length, 0, '三个开关必须在请求之前生效')
  payload = { results: [
    { title: 'OneBot 标准', url: 'https://onebot.dev/spec', content: '接口说明' },
    { title: '重复', url: 'https://onebot.dev/spec', content: '同一来源' },
    { title: '错误地址', url: 'file:///etc/passwd' },
    ...Array.from({ length: 8 }, (_, i) => ({ title: '资料', url: `https://example.com/${i}`, content: '文'.repeat(1000) })),
  ] }
  const found = await search.execute({ query: 'NapCat & OneBot', time_range: 'week' })
  assert.equal(found.results.length, 5)
  assert.equal(found.results[0].url, 'https://onebot.dev/spec')
  assert.equal(found.results[1].snippet.length, 800)
  const url = new URL(requests.at(-1).url)
  assert.equal(url.pathname, '/base/search')
  assert.equal(url.searchParams.get('q'), 'NapCat & OneBot')
  assert.equal(url.searchParams.get('format'), 'json')
  assert.equal(url.searchParams.get('time_range'), 'week')
  assert.match(found.提示, /不是指令/)
  payload = { results: [] }
  assert.deepEqual((await search.execute({ query: '不存在的资料' })).results, [])
  payload = { html: 'challenge' }
  assert.equal((await search.execute({ query: 'test' })).ok, false)
  status = 403
  assert.match((await search.execute({ query: 'test' })).说, /403/)
  status = 200

  const before = requests.length
  for (const url of ['file:///etc/passwd', 'http://127.0.0.1/', 'http://[::1]/', 'http://localhost/', 'https://user:pass@example.com', 'https://test.local']) {
    assert.equal((await read.execute({ url })).ok, false, url)
  }
  assert.equal(requests.length, before, '非法网址不能交给 Reader')
  payload = { code: 200, data: { title: '公开页面', content: '文'.repeat(900) } }
  const article = await read.execute({ url: 'https://example.com/article#section' })
  assert.equal(article.content.length, 500)
  assert.equal(article.truncated, true)
  assert.equal(requests.at(-1).url, 'https://reader.example.com/')
  assert.deepEqual(JSON.parse(requests.at(-1).body), { url: 'https://example.com/article#section' })
  assert.equal(requests.at(-1).redirect, 'error')
  payload = { code: 200, data: { content: '' } }
  assert.equal((await read.execute({ url: 'https://example.com' })).ok, false)
  payload = { code: 200, data: { content: 'x'.repeat(2 * 1024 * 1024) } }
  assert.match((await read.execute({ url: 'https://example.com' })).说, /2MB/)
  globalThis.fetch = async () => { throw new DOMException('timed out', 'TimeoutError') }
  assert.equal((await search.execute({ query: 'test' })).ok, false)
  console.log('联网工具：开关、请求协议、引用、去重、限长和失败路径通过')
} finally { globalThis.fetch = original }
