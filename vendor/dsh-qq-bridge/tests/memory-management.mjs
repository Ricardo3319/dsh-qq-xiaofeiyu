import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { 建共同记忆 } from '../lib/共同记忆.js'

const dir = mkdtempSync(join(tmpdir(), 'qq-memory-management-'))
const file = join(dir, 'memory.json')
const now = Date.now(), day = 86400000
const group = { 来源: '群', 哪: '100' }, other = { 来源: '群', 哪: '200' }
const privateChat = { 来源: '私聊', 哪: '100' }
const row = (说, extra = {}) => ({ 说, 时: now, ...group, 类: '事实', 涉及: ['123'], ...extra })
try {
  const original = [row('小明喜欢蓝色'), row('小明喜欢蓝色杯子'),
    row('小明喜欢蓝色', other), row('小明喜欢蓝色', privateChat),
    row('已经改口的约定', { 类: '约定', 失效: now }),
    row('过期的一次活动', { 类: '事件', 时: now - 100 * day }),
    row('仍未完成的约定', { 类: '约定', 时: now - 500 * day })]
  writeFileSync(file, JSON.stringify({ version: 1, 条目: original }))
  let memory = 建共同记忆(file)
  let list = memory.列(group)
  assert.equal(list.total, 3, '只列本群有效记忆，排除其他群/私聊/过期/失效项')
  assert.deepEqual(memory.列({ ...group, who: '999' }).results, [])
  assert.equal(memory.列({ ...group, 类: '约定' }).total, 1)
  assert.equal(memory.列({ 来源: '群' }).total, 0)
  const saved = JSON.parse(readFileSync(file, 'utf8'))
  assert.deepEqual(saved.条目.map(({ id, ...x }) => x), original, '补编号不能改已有内容和元数据')
  const id = list.results.find(x => x.说 === '小明喜欢蓝色').id
  memory = 建共同记忆(file)
  assert.equal(memory.列(group).results.find(x => x.说 === '小明喜欢蓝色').id, id, '重启后编号保持')
  assert.equal(memory.查({ ...group, 线索: '蓝色' }).find(x => x.哪 === '100' && x.说 === '小明喜欢蓝色').id, id)

  assert.equal(memory.忘({ ...group, 片段: '蓝色' }).ok, false, '片段歧义不能批量删除')
  assert.equal(memory.记({ ...group, 说: '小明改喜欢红色', 取代: '蓝色' }).ok, false, '歧义取代不能顺便新增')
  assert.equal(memory.数量(), original.length)
  assert.equal(memory.改({ ...other, id, 说: '跨群修改' }).ok, false)
  assert.equal(memory.忘({ ...privateChat, id }).ok, false, '号码相同但来源不同也不能删')
  assert.equal(memory.改({ ...group, id, 说: ' ' }).ok, false)
  assert.equal(memory.改({ ...group, id, 说: '有效内容', 类: '随便' }).ok, false)
  const changed = memory.改({ ...group, id, 说: '小明喜欢绿色', 类: '事实' })
  assert.equal(changed.ok, true)
  assert.equal(changed.result.id, id)
  assert.equal(changed.result.日期, new Date(now).toISOString().slice(0, 10))
  assert.deepEqual(changed.result.涉及, ['123'])
  assert.equal(建共同记忆(file).列(group).results.find(x => x.id === id).说, '小明喜欢绿色')
  assert.equal(memory.列(other).results[0].说, '小明喜欢蓝色')
  assert.equal(memory.列(privateChat).results[0].说, '小明喜欢蓝色')

  const replacement = memory.记({ ...group, 说: '小明改喜欢红色杯子', 取代: '蓝色杯子' })
  assert.equal(replacement.ok, true)
  assert.equal(memory.列(group).results.some(x => x.说 === '小明喜欢蓝色杯子'), false)
  assert.equal(memory.列(other).results.length, 1)
  const beforeMissing = memory.数量()
  assert.equal(memory.记({ ...group, 说: '不该新增', 取代: '根本没有的记录' }).ok, false)
  assert.equal(memory.数量(), beforeMissing)
  assert.equal(memory.忘({ ...group, id: replacement.id }).删, 1)
  const afterDelete = memory.记({ ...group, 说: '新增一条事实' })
  assert.ok(afterDelete.id > replacement.id, '已删除的编号不能分配给另一件事')
  assert.equal(memory.忘({ ...group, id: replacement.id }).ok, false, '旧编号不能误删新条目')

  // 无法落盘时，三个写操作都必须报告失败，内存和磁盘继续保持原内容。
  const beforeFailure = readFileSync(file, 'utf8')
  const beforeState = structuredClone(memory.原始())
  mkdirSync(file + '.tmp')
  assert.equal(memory.改({ ...group, id, 说: '写不进去的修改' }).ok, false)
  assert.equal(memory.忘({ ...group, id }).ok, false)
  assert.equal(memory.记({ ...group, 说: '写不进去的新增', 取代: '绿色' }).ok, false)
  assert.equal(readFileSync(file, 'utf8'), beforeFailure)
  assert.deepEqual(memory.原始(), beforeState)
  rmSync(file + '.tmp', { recursive: true })

  const pages = 建共同记忆(join(dir, 'pages.json'))
  for (let i = 0; i < 12; i++) assert.equal(pages.记({ ...group, 说: `事件 ${i}` }).ok, true)
  const first = pages.列(group), second = pages.列({ ...group, offset: first.next_offset })
  assert.equal(first.results.length, 10)
  assert.equal(second.results.length, 2)
  assert.equal(second.next_offset, null)
  assert.equal(new Set([...first.results, ...second.results].map(x => x.id)).size, 12)
  assert.equal(pages.列({ ...group, offset: -1 }).ok, false)
  console.log('记忆管理：编号迁移/重启、分页、来源隔离、歧义拒绝、精确纠正/删除、取代和落盘失败通过')
} finally { rmSync(dir, { recursive: true, force: true }) }
