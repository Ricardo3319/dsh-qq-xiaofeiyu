import assert from 'node:assert/strict'
import { 规整互动, 判互动 } from '../lib/互动节奏.js'
const settings = { quiet_start: '01:00', quiet_end: '08:00', timezone: 'Asia/Shanghai', min_interval_minutes: 20, weekday_interval_minutes: 60 }
const at = s => Date.parse(s)
const judge = (s, last = 0, config = settings) => 判互动(config, last, at(s))
assert.equal(judge('2026-11-06T00:59:59+08:00').allowed, true)
assert.equal(judge('2026-11-06T01:00:00+08:00').allowed, false)
assert.equal(judge('2026-11-06T08:00:00+08:00').allowed, true)
const overnight = { ...settings, quiet_start: '23:00', quiet_end: '08:00' }
assert.equal(judge('2026-11-06T23:00:00+08:00', 0, overnight).quiet, true)
assert.equal(judge('2026-11-07T07:59:00+08:00', 0, overnight).quiet, true)
assert.equal(judge('2026-11-07T08:00:00+08:00', 0, overnight).quiet, false)
assert.equal(judge('2026-11-06T09:20:00+08:00', at('2026-11-06T09:00:00+08:00')).allowed, false)
assert.equal(judge('2026-11-06T10:00:00+08:00', at('2026-11-06T09:00:00+08:00')).allowed, true)
assert.equal(judge('2026-11-07T09:20:00+08:00', at('2026-11-07T09:00:00+08:00')).allowed, true)
assert.equal(judge('2026-11-07T09:19:59+08:00', at('2026-11-07T09:00:00+08:00')).allowed, false)
assert.equal(judge('2026-11-06T07:30:00+08:00', 0, { ...settings, timezone: 'Asia/Tokyo' }).quiet, false)
assert.equal(judge('2026-11-08T23:30:00Z').interval_minutes, 60, '星期按配置时区计算')
assert.equal(judge('2026-11-06T02:00:00+08:00', 0, {}).allowed, true, '旧绑定没有设置时不改变行为')
for (const patch of [{ quiet_start: '24:00' }, { quiet_end: '1:00' }, { timezone: 'Mars/Test' },
  { timezone: '' }, { min_interval_minutes: -1 }, { min_interval_minutes: 1.5 }, { weekday_interval_minutes: 1441 }]) {
  assert.throws(() => 规整互动({ ...settings, ...patch }))
  assert.equal(判互动({ ...settings, ...patch }).allowed, false)
}
console.log('互动策略：时区、跨午夜、起止边界、工作日/周末间隔、旧配置和非法设置通过')
