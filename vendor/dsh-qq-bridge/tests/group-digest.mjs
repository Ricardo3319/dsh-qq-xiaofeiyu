import assert from 'node:assert/strict'
import { 建群聊摘要 } from '../lib/群聊摘要.js'

const oldNow = Date.now
let now = 1800000000000
Date.now = () => now
const row = (id, text, age = 0, extra = {}) => ({ message_id: id, time: (now - age) / 1000,
  user_id: 123, sender: { card: '小明', nickname: '名字' },
  message: [{ type: 'text', data: { text } }], ...extra })
try {
  const cache = 建群聊摘要()
  assert.equal(cache.查('111').last_polled_at, null)
  assert.deepEqual(cache.查('111').messages, [])
  cache.收('111', [row(1, '提议周五上线', 5000), row(2, '时间还没定', 4000), row(2, '时间还没定', 4000),
    row(3, '范围之外', 3600001), row(4, '过期', 86400001), row(5, '未来', -1000),
    row(6, '其他群', 0, { group_id: 222 }), row(7, '私聊', 0, { message_type: 'private' })])
  cache.收('222', [row(1, '另一个群的同号消息')])
  const first = cache.查('111')
  assert.deepEqual(first.messages.map(x => x.id), ['1', '2'])
  assert.equal(first.messages[0].sender, '小明')
  assert.equal(first.messages[0].sender_id, '123')
  assert.equal(first.available_count, 2)
  assert.equal(first.partial, true, '不能声称轮询缓存是完整历史')
  assert.deepEqual(first.covered_range, { from: new Date(now - 5000).toISOString(), to: new Date(now - 4000).toISOString() })
  assert.equal(cache.查('111', { minutes: 120 }).messages.length, 3)
  assert.equal(cache.查('222').messages[0].text, '另一个群的同号消息')
  for (const minutes of [0, 1441, 1.5, '60']) assert.equal(cache.查('111', { minutes }).ok, false)
  assert.equal(cache.查('111', { before_id: '不存在' }).ok, false)
  cache.收('111', [row(1, '修改后的消息', 5000)])
  assert.equal(cache.查('111').messages[0].text, '修改后的消息')
  assert.equal(cache.查('111').messages.length, 2, '重复轮询不能重复计数')

  cache.收('media', [row(10, '', 0, { message: [
    { type: 'text', data: { text: '看这里' } },
    { type: 'at', data: { qq: '456' } }, { type: 'reply', data: { id: 9 } },
    { type: 'image', data: { url: 'https://example.invalid/private-image' } },
    { type: 'record', data: { file: 'private-audio' } },
    { type: 'forward', data: { id: 'private-forward' } },
  ] })])
  const media = cache.查('media').messages[0].text
  assert.match(media, /@456/)
  assert.match(media, /引用消息 9/)
  assert.match(media, /图片，未解析/)
  assert.match(media, /语音，未解析/)
  assert.doesNotMatch(media, /private-/)

  cache.收('pages', Array.from({ length: 170 }, (_, i) => row(i, `讨论 ${i}`, 200000 - i * 1000)))
  let page = cache.查('pages'), seen = []
  assert.equal(page.messages.length, 80)
  while (true) {
    seen.push(...page.messages.map(x => x.id))
    if (!page.more_available) break
    page = cache.查('pages', { before_id: page.next_before_id })
  }
  assert.equal(seen.length, 170)
  assert.equal(new Set(seen).size, 170, '同秒消息也不能跨页重复或漏掉')
  cache.收('same-second', Array.from({ length: 90 }, (_, i) => row(i, '同秒消息')))
  const same = cache.查('same-second')
  const rest = cache.查('same-second', { before_id: same.next_before_id })
  assert.equal(new Set([...same.messages, ...rest.messages].map(x => x.id)).size, 90)

  cache.收('long', Array.from({ length: 30 }, (_, i) => row(i, '字'.repeat(999) + '😀尾巴')))
  const long = cache.查('long')
  assert.equal(long.truncated_count, long.messages.length)
  assert.ok(long.more_available)
  assert.ok(long.messages.reduce((s, x) => s + x.text.length, 0) <= 12000)
  assert.ok(long.messages.every(x => !/[\uD800-\uDBFF]$/.test(x.text)))
  cache.收('limit', Array.from({ length: 510 }, (_, i) => row(i, `消息 ${i}`, 600000 - i * 1000)))
  assert.equal(cache.查('limit').available_count, 500)

  cache.保留群(['111'])
  assert.equal(cache.查('222').messages.length, 0)
  now += 86400001
  assert.equal(cache.查('111', { minutes: 1440 }).messages.length, 0)
  assert.equal(cache.查('111').last_polled_at, null)
  assert.equal(建群聊摘要().查('111').available_count, 0, '新实例不恢复旧缓存')
  console.log('群聊摘要：隔离、去重、时间范围、分页、附件标记、字数/容量上限、过期与清理通过')
} finally { Date.now = oldNow }
