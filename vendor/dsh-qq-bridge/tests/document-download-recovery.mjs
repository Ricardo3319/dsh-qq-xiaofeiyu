import assert from 'node:assert/strict'
import { 建聊天文档 } from '../lib/聊天文档.js'
const oldFetch = fetch
async function scenario({ status = 403, type = '群', fileId = true, url = 'https://file.invalid/old', finalStatus = 200, large = false, networkError = false } = {}) {
  const docs = 建聊天文档(), row = { 类型: type, 号码: '123' }, downloads = [], calls = []
  docs.收(row, [{ message_id: 1, time: Math.floor(Date.now()/1000), message: [{ type: 'file', data: {
    name: '测试.txt', url, ...(fileId ? { file_id: 'test-id' } : {}),
  } }] }])
  globalThis.fetch = async (link, options) => {
    downloads.push(link)
    assert.equal(options.headers, undefined)
    if (networkError) throw Error('network failed')
    return new Response('已恢复正文', { status: link.endsWith('/old') ? status : finalStatus,
      headers: large ? { 'content-length': '11000000' } : {} })
  }
  const call = async (action, params) => { calls.push({ action, params }); return { url: 'https://file.invalid/new' } }
  const args = { document_id: 'doc-1-0' }
  const [result, concurrent] = await Promise.all([docs.读(row, args, call), docs.读(row, args, call)])
  assert.deepEqual(result, concurrent, '并发应共享本次下载/刷新')
  if (result.ok) {
    const before = downloads.length
    assert.equal((await docs.读(row, args, call)).content, result.content)
    assert.equal(downloads.length, before, '成功后使用正文缓存')
  }
  return { result, downloads, calls }
}
try {
  for (const status of [401,403,404,410]) {
    const r = await scenario({ status })
    assert.equal(r.result.ok, true); assert.equal(r.result.content, '已恢复正文')
    assert.equal(r.downloads.length, 2)
    assert.deepEqual(r.calls, [{ action: 'get_group_file_url', params: { group_id: '123', file_id: 'test-id' } }])
  }
  const p = await scenario({ type: '私聊' })
  assert.deepEqual(p.calls, [{ action: 'get_private_file_url', params: { user_id: '123', file_id: 'test-id' } }])
  const failed = await scenario({ finalStatus: 403 })
  assert.equal(failed.result.ok, false);assert.equal(failed.downloads.length, 2);assert.equal(failed.calls.length, 1)
  for (const options of [{ status: 500 }, { fileId: false }, { status: 200, large: true }, { networkError: true }, { url: 'file:///etc/passwd' }]) {
    const r = await scenario(options)
    assert.equal(r.result.ok, false);assert.equal(r.calls.length, 0, '不为非过期错误刷新链接')
    assert.ok(r.downloads.length <= 1)
  }
  console.log('文件链接恢复：群/私聊、四类失效状态、仅刷新一次、并发共享和正文缓存；非失效错误不重试通过')
} finally { globalThis.fetch = oldFetch }
