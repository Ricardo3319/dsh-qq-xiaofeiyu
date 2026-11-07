// 每个 QQ 聊天的免打扰与主动互动间隔。相同起止表示不设安静时段。
export function 规整互动(raw = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('互动设置必须是对象。')
  const out = { quiet_start: '00:00', quiet_end: '00:00', timezone: 'Asia/Shanghai',
    min_interval_minutes: 0, weekday_interval_minutes: 0, ...raw }
  for (const key of ['quiet_start', 'quiet_end']) {
    if (typeof out[key] !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(out[key])) throw new Error('免打扰时间请使用 HH:MM（00:00–23:59）。')
  }
  if (typeof out.timezone !== 'string' || !out.timezone.trim()) throw new Error('请填写时区，例如 Asia/Shanghai。')
  try { new Intl.DateTimeFormat('en-US', { timeZone: out.timezone }).format() }
  catch { throw new Error('时区无效，请使用 Asia/Shanghai、Asia/Tokyo 等时区名。') }
  for (const key of ['min_interval_minutes', 'weekday_interval_minutes']) {
    if (!Number.isInteger(out[key]) || out[key] < 0 || out[key] > 1440) throw new Error('互动间隔必须是 0–1440 的整数分钟。')
  }
  return { quiet_start: out.quiet_start, quiet_end: out.quiet_end, timezone: out.timezone,
    min_interval_minutes: out.min_interval_minutes, weekday_interval_minutes: out.weekday_interval_minutes }
}

export function 判互动(raw, 上次 = 0, 现在 = Date.now()) {
  let 设置
  try { 设置 = 规整互动(raw) }
  catch (e) { return { allowed: false, reason: '互动设置无效：' + e.message } }
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 设置.timezone, weekday: 'short',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(现在))
  const 值 = Object.fromEntries(parts.map(x => [x.type, x.value]))
  const 分钟 = Number(值.hour) * 60 + Number(值.minute)
  const 分 = s => Number(s.slice(0, 2)) * 60 + Number(s.slice(3))
  const 起 = 分(设置.quiet_start), 止 = 分(设置.quiet_end)
  const quiet = 起 !== 止 && (起 < 止 ? 分钟 >= 起 && 分钟 < 止 : 分钟 >= 起 || 分钟 < 止)
  const weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].includes(值.weekday)
  const interval_minutes = Math.max(设置.min_interval_minutes, weekday ? 设置.weekday_interval_minutes : 0)
  if (quiet) return { allowed: false, reason: `免打扰 ${设置.quiet_start}–${设置.quiet_end}（${设置.timezone}）`, quiet, interval_minutes }
  const remaining_ms = 上次 ? Math.max(0, 上次 + interval_minutes * 60000 - 现在) : 0
  return { allowed: !remaining_ms, quiet, interval_minutes, remaining_ms,
    reason: remaining_ms ? `主动互动间隔未到，还需 ${Math.ceil(remaining_ms / 60000)} 分钟` : '当前可以主动互动' }
}
