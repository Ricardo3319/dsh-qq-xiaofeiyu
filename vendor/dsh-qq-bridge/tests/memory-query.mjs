import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { 建共同记忆 } from '../lib/共同记忆.js'

const dir = mkdtempSync(join(tmpdir(), 'qq-memory-query-'))
const file = join(dir, 'memory.json')
const now = Date.now(), day = 86400000
const row = (说, extra = {}) => ({ 说, 时: now, 来源: '群', 哪: '100', 类: '事实', ...extra })
try {
  writeFileSync(file, JSON.stringify({ version: 1, 条目: [
    row('小明在准备考研'), row('小红昨天在群里说今天吃火锅'),
    row('答应周五交考研资料', { 类: '约定', 时: now - 500 * day }),
    row('小明考研已经取消', { 失效: now }),
    row('考研报名已经结束', { 类: '事件', 时: now - 100 * day }),
    row('小明考研的私事', { 来源: '私聊', 哪: '111' }),
    row('另一个人的考研私事', { 来源: '私聊', 哪: '222' }),
    row('NapCat 支持 OneBot'),
  ] }))
  const memory = 建共同记忆(file)
  const r = memory.查({ 来源: '群', 哪: '100', 线索: '小明考研' })
  assert.equal(r[0].说, '小明在准备考研')
  assert.ok(r.some(x => x.类 === '约定'), '未完成约定不能按事件的过期天数淘汰')
  assert.ok(r.every(x => x.来源 === '群' && !/取消|结束|火锅/.test(x.说)))
  assert.match(r[0].日期, /^\d{4}-\d{2}-\d{2}$/)
  assert.deepEqual(memory.查({ 来源: '群', 线索: '火星殖民地' }), [], '无命中不能退回最近记录')
  assert.deepEqual(memory.查({ 来源: '群', 线索: '！？' }), [])
  const privateRows = memory.查({ 来源: '私聊', 哪: '111', 线索: '考研' })
  assert.deepEqual(privateRows.map(x => x.说), ['小明考研的私事'])
  assert.deepEqual(memory.查({ 来源: '私聊', 线索: '考研' }), [])
  assert.equal(memory.查({ 来源: '群', 线索: 'onebot' })[0].说, 'NapCat 支持 OneBot')
  assert.equal(memory.查({ 来源: '群', 线索: '考研', 类: '约定' }).length, 1)
  assert.equal(memory.数量(), 8, '只读检索不能改动原有记忆')
  console.log('主动回忆：关键词、时效、取代、类型、私聊隔离和无命中路径通过')
} finally { rmSync(dir, { recursive: true, force: true }) }
