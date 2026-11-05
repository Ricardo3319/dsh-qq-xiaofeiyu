import assert from 'node:assert/strict'
import { 认模型图 } from '../lib/host.js'

const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0])
assert.deepEqual(认模型图(png), { 类: 'image/png', 给模型: true })

const jpg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0])
assert.deepEqual(认模型图(jpg), { 类: 'image/jpeg', 给模型: true })

const webp = Buffer.alloc(12)
webp.write('RIFF', 0)
webp.write('WEBP', 8)
assert.deepEqual(认模型图(webp), { 类: 'image/webp', 给模型: true })

const ico = Buffer.alloc(12)
ico[2] = 1
assert.deepEqual(认模型图(ico), { 类: 'image/x-icon', 给模型: true })

const gif = Buffer.alloc(12)
gif.write('GIF89a', 0)
assert.deepEqual(认模型图(gif), { 类: 'image/gif', 给模型: false })

const html = Buffer.from('<html>nope!!')
assert.deepEqual(认模型图(html), { 类: '', 给模型: false })
assert.equal(认模型图(Buffer.alloc(4)).给模型, false)

console.log('认模型图：过')
