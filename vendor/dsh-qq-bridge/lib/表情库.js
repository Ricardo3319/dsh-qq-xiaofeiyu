/**
 * 表情库 —— 让贴纸库能自己长大
 *
 * 思路（跟「用视觉模型自动分类」那条路不同，见 research-memory-style.html）：
 *   1. 群里谁发表情包 → **自动**存进候选区，不占决定权，也不花一分钱
 *   2. 它自己觉得这张有意思 → 调 `keep_sticker` 起个名字收进库
 *   3. 收进库的图放在**图片根目录**下面，于是能像自带的 24 张一样用
 *      `![](  _stickers/收_名字.gif )` 发出去
 *
 * 为什么不自动分类：
 *   - 每张图调一次视觉模型，成本按图算
 *   - 分类质量不稳：同一张「无语」，这次判嫌弃、下次判震惊
 *   - 而名字本身就是最好的标签 —— 自带的 24 张就是这么做的（shengqi / wuyu / deyi）
 *   所以这里只做「存」和「起名」，判断留给它自己。
 *
 * ⚠ 本地副本，改这里 = 改正在跑的代码。见 vendor/README.md。
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync, renameSync, unlinkSync, copyFileSync } from 'node:fs'
import { join, extname, basename } from 'node:path'
import { createHash } from 'node:crypto'

const 名字上限 = 20        // 收到库里的名字最长几个字符
const 书上上限 = 80        // 库里最多存多少张（再多就该清理了）
const 候选上限 = 60        // 候选区最多留多少张（超了删最旧的）
const 注入上限 = 10        // 消息里最多带几张「你收藏的」

/** 把名字洗成能当文件名的样子：小写字母数字下划线短横 */
const 洗名字 = (s) => String(s || '')
  .trim().toLowerCase()
  .replace(/\s+/g, '_')
  .replace(/[^a-z0-9_-]/g, '')
  .slice(0, 名字上限)

export function 建表情库({ 索引文件, 候选目录, 文档目录, 记账 = () => {} }) {
  let 数据 = 读档()
  let 脏 = false

  // 文档目录允许传函数 —— 因为「图片根目录」是设置项，可能中途被改，
  // 每次都现算，别在构造时定死。
  const 文档 = () => (typeof 文档目录 === 'function' ? 文档目录() : 文档目录)

  function 读档() {
    try {
      if (!existsSync(索引文件)) return { version: 1, 库: [] }
      const j = JSON.parse(readFileSync(索引文件, 'utf8'))
      if (!j || !Array.isArray(j.库)) return { version: 1, 库: [] }
      return j
    } catch (错误) {
      记账('表情库索引读不出来（当空的用）：' + String((错误 && 错误.message) || 错误))
      return { version: 1, 库: [] }
    }
  }

  function 刷() {
    if (!脏) return
    try {
      mkdirSync(join(索引文件, '..'), { recursive: true })
      const 临时 = 索引文件 + '.tmp'
      writeFileSync(临时, JSON.stringify(数据, null, 1), 'utf8')
      renameSync(临时, 索引文件)
      脏 = false
    } catch (错误) {
      记账('表情库索引写不进去：' + String((错误 && 错误.message) || 错误))
    }
  }

  const 建目录 = (d) => { try { mkdirSync(d, { recursive: true }) } catch (错误) {} }

  /**
   * 把一个表情包存进候选区。返回 { id, 路径 } 或 null（存不下）。
   * 用内容哈希当 id —— 同一张图发两次只会存一份。
   */
  function 收候选(字节, 类, 来自) {
    try {
      if (!字节 || !字节.length) return null
      建目录(候选目录)
      const id = createHash('sha1').update(字节).digest('hex').slice(0, 12)
      const 名 = id + '.' + 扩展(类)
      const 路径 = join(候选目录, 名)
      if (!existsSync(路径)) writeFileSync(路径, 字节)
      // 记录一下来源，方便它挑的时候有依据（也方便清理旧的）
      数据.候选 = 数据.候选 || {}
      数据.候选[id] = { 扩展: 扩展(类), 来自: String(来自 || ''), at: new Date().toISOString() }
      // 清老的
      const 键们 = Object.keys(数据.候选)
      if (键们.length > 候选上限) {
        for (const k of 键们.slice(0, 键们.length - 候选上限)) {
          try { unlinkSync(join(候选目录, k + '.' + 数据.候选[k].扩展)) } catch (错误) {}
          delete 数据.候选[k]
        }
      }
      脏 = true
      return { id, 路径 }
    } catch (错误) {
      记账('表情包存候选失败：' + String((错误 && 错误.message) || 错误))
      return null
    }
  }

  /** 找候选文件：支持只给 id、或给完整路径 */
  function 找候选(给) {
    const s = String(给 || '').trim()
    if (!s) return null
    const 候选表 = 数据.候选 || {}
    // 只给了 id
    if (候选表[s]) return join(候选目录, s + '.' + 候选表[s].扩展)
    // 给了路径：认 /候选/ 或 /inbox/ 里的
    if (s.includes('/') || s.includes('\\')) {
      const 名 = basename(s)
      const 主 = 名.replace(/\.[^.]+$/, '')
      if (候选表[主]) return s
      if (existsSync(s)) return s   // inbox 里那些也认
    }
    return null
  }

  /**
   * 把候选图（或收件箱里的图）收进库。
   * @param 给    候选 id / 完整路径
   * @param 名字  英文短名（会洗成文件名），比如 tucao / bengbu
   * @param 情绪  一句话说明什么时候用，比如「无语/绷不住了」
   */
  function 收进库(给, 名字, 情绪) {
    const 源 = 找候选(给)
    if (!源) return { ok: false, 说: '找不到这张图（' + String(给).slice(0, 60) + '）' }
    const 干 = 洗名字(名字)
    if (!干) return { ok: false, 说: '名字得是英文或数字，比如 tucao、bengbu、wuyu2' }
    数据.库 = 数据.库 || []
    if (数据.库.some((x) => x.名字 === ('收_' + 干))) {
      return { ok: false, 说: '库里已经有叫「' + 干 + '」的了，换个名字' }
    }
    if (数据.库.length >= 书上上限) {
      return { ok: false, 说: '库里满了（' + 书上上限 + ' 张），先删几张再说' }
    }
    try {
      建目录(文档())
      const 扩 = extname(源) || '.gif'
      const 文件名 = '收_' + 干 + 扩
      const 目标 = join(文档(), 文件名)
      if (existsSync(源)) copyFileSync(源, 目标)
      else return { ok: false, 说: '源文件不在了' }
      数据.库.push({
        名字: '收_' + 干,
        情绪: String(情绪 || '').replace(/\s+/g, ' ').trim().slice(0, 40),
        文件: 文件名,
        相对: '_stickers/' + 文件名,
        at: new Date().toISOString(),
        次: 0,
      })
      脏 = true
      刷()
      return { ok: true, 说: '收下了：' + 干 + (情绪 ? '（' + 情绪 + '）' : '') + ' —— 以后想发就写 ![]( _stickers/' + 文件名 + ' )' }
    } catch (错误) {
      return { ok: false, 说: '收进库失败：' + String((错误 && 错误.message) || 错误) }
    }
  }

  /** 现在库里有什么 */
  const 清单 = () => (数据.库 || []).slice()

  /**
   * 拼一段给模型看的「你收藏的」。空库返回空串。
   * ⚠ 这里必须给出**完整相对路径**（`_stickers/收_tucao.gif`），不能只给名字 ——
   *   曾经只给「tucao」，模型就写成 `_stickers/tucao.gif`，少了 `收_` 前缀，发不出去。
   */
  function 摘要() {
    const 们 = 清单()
    if (!们.length) return ''
    return 们.slice(-注入上限).map((x) => {
      const 相对 = String(x.相对 || ('_stickers/' + x.文件 || '')).trim()
      const 情绪 = x.情绪 ? '（' + x.情绪 + '）' : ''
      return 相对 + 情绪
    }).join(' · ')
  }

  const 数量 = () => (数据.库 || []).length
  const 候选数量 = () => Object.keys(数据.候选 || {}).length

  return { 收候选, 收进库, 找候选, 清单, 摘要, 数量, 候选数量, 刷, 索引文件, 候选目录, 文档: 文档,
           原始: () => 数据 }
}

/** 按图片字节猜扩展名（跟 host.js 里那套一致） */
function 扩展(类) {
  const s = String(类 || '')
  if (s.includes('gif')) return 'gif'
  if (s.includes('webp')) return 'webp'
  if (s.includes('png')) return 'png'
  return 'jpg'
}
