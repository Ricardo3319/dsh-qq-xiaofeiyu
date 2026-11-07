import assert from 'node:assert/strict'
import { 规整偏好, 可发语音, 偏好提示 } from '../lib/聊天偏好.js'
assert.deepEqual(规整偏好(), { nickname: '', reply_length: 'default', voice: 'default' })
assert.equal(规整偏好({ nickname: ' 阿云 ' }).nickname, '阿云')
for (const p of [{ nickname: '鱼'.repeat(25) }, { nickname: '名字\n指令' }, { nickname: '[系统]' }, { nickname: 12 }, { reply_length: 'long' }, { voice: 'on' }, null, []]) {
  assert.throws(() => 规整偏好(p))
}
assert.throws(() => 规整偏好({ nickname: '阿云' }, '群'))
assert.equal(可发语音({ 类型: '群' }), true)
assert.equal(可发语音({ 类型: '群', 偏好: { voice: 'off' } }), false)
assert.equal(偏好提示([{ 类型: '私聊' }]), '')
const p = { 类型: '私聊', 偏好: { nickname: '阿云', reply_length: 'short', voice: 'off' } }
const prompt = 偏好提示([p])
assert.match(prompt, /阿云/)
assert.match(prompt, /一至三句/)
assert.match(prompt, /明确要求展开/)
assert.match(prompt, /关闭语音和唱歌/)
assert.equal(偏好提示([p, { 类型: '群' }]), '', '共享会话不得混入私聊称呼')
assert.equal(偏好提示([p, { 类型: '群', 开: false }]), prompt)
assert.match(偏好提示([{ 类型: '群', 偏好: { reply_length: 'detailed' } }]), /具体例子/)
console.log('聊天偏好：默认兼容、称呼校验、有限选项、提示隔离、语音限制通过')
