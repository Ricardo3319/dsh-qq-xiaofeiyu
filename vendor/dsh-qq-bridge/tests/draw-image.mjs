import assert from 'node:assert/strict'
import { 生图取字节 } from '../lib/host.js'

const jpeg = Buffer.alloc(32)
jpeg[0] = 0xff; jpeg[1] = 0xd8; jpeg[2] = 0xff
const base = 'http://127.0.0.1:3425/v1/images/generations'

// b64_json：直接解出来
const got = await 生图取字节({ data: [{ b64_json: jpeg.toString('base64') }] }, base)
assert.deepEqual(got, jpeg)

// 没有 data / 空图
assert.equal(await 生图取字节({}, base), null)
assert.equal(await 生图取字节({ data: [] }, base), null)
assert.equal(await 生图取字节({ data: [{ b64_json: '' }] }, base), null)

// 外站 URL 不抓
const originalFetch = globalThis.fetch
let fetched = ''
globalThis.fetch = async (u) => { fetched = String(u); return { ok: true, arrayBuffer: async () => jpeg } }
assert.equal(await 生图取字节({ data: [{ url: 'https://evil.example/x.png' }] }, base), null)
assert.equal(fetched, '')

// 本机 URL 可以抓
const local = await 生图取字节({ data: [{ url: 'http://127.0.0.1:3425/files/x.png' }] }, base)
assert.deepEqual(local, jpeg)
assert.match(fetched, /127\.0\.0\.1/)

globalThis.fetch = originalFetch
console.log('生图取字节：过')