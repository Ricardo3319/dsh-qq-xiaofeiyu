/**
 * 群友簿 —— 记住「谁是谁」
 *
 * 为什么单独做一份，而不用「鱼的记忆」那套检索：
 *   那套的核心是**按相似度捞**（`问句信息量` 只统计记忆库里已出现的词）。
 *   库小的时候这是死循环：库太空 → 门永远打不开 → 库更空。
 *   实测 100 次检索里只有 2 次越过门槛，攒下的记忆 1~2 条。
 *
 *   而「谁是谁」根本不需要检索 —— **谁说话就带谁那一份**，确定性注入。
 *   你能听见山鬼说话，就该知道他上次说过什么。
 *
 * 存的是：昵称 / 别名 / 见过几次 / 第一面 / 最近一面 / 印象若干条。
 * 印象由模型自己调工具写（见 host.js 的 `记群友`），这里只管存取。
 *
 * ⚠ 这是 ~/agents/QQ_ds/vendor/ 下的本地副本，跟 vendor/README.md 里说的一样：
 *   profile 用 link: 指过来，改这里 = 改正在跑的代码。
 */

import { readFileSync, writeFileSync, existsSync, renameSync } from 'node:fs'

const 印象上限 = 12   // 每人最多留几条印象（超了丢最旧的）
const 印象字数 = 80   // 单条印象最长几个字
const 注入条数 = 4    // 注入时最多带几条印象（带太多反而吵）

export function 建群友簿(文件, 记账 = () => {}) {
  let 数据 = 读档()
  let 脏 = false

  function 读档() {
    try {
      if (!existsSync(文件)) return { version: 1, 人: {} }
      const j = JSON.parse(readFileSync(文件, 'utf8'))
      if (!j || typeof j !== 'object' || !j.人 || typeof j.人 !== 'object') {
        return { version: 1, 人: {} }
      }
      return j
    } catch (错误) {
      记账('群友簿读不出来（当空的用）：' + String((错误 && 错误.message) || 错误))
      return { version: 1, 人: {} }
    }
  }

  /** 写盘：先写临时文件再改名，别让半截文件把上一份好数据顶掉 */
  function 刷() {
    if (!脏) return
    try {
      const 临时 = 文件 + '.tmp'
      writeFileSync(临时, JSON.stringify(数据, null, 1), 'utf8')
      renameSync(临时, 文件)
      脏 = false
    } catch (错误) {
      记账('群友簿写不进去：' + String((错误 && 错误.message) || 错误))
    }
  }

  const 清 = (s, n) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim().slice(0, n)

  const 取人 = (号码) => 数据.人[String(号码 || '').trim()] || null

  /**
   * 记一次「见到」：更新昵称、末见时间、条数。
   * ⚠ 只改内存，不写盘 —— 调用方在一批处理完之后调 刷()，别每条消息都写一次文件。
   * ⚠ 身份**只认 QQ 号**（群名片随时会改，昵称不可靠）；昵称只是拿来显示的，不参与认人。
   */
  function 见(号码, 昵称) {
    const k = String(号码 || '').trim()
    if (!k) return null
    const 新名 = 清(昵称, 24)
    let 人 = 数据.人[k]
    if (!人) {
      人 = { 号码: k, 昵称: 新名, 首见: new Date().toISOString(),
             末见: '', 条数: 0, 印象: [] }
      数据.人[k] = 人
    } else if (新名 && 新名 !== 人.昵称) {
      // 换了群名片：直接覆盖。不留旧名 —— 旧名对新名字没有意义，
      // 而且按名字认人正是要避免的事（两个人可能撞名）。
      人.昵称 = 新名
    }
    人.末见 = new Date().toISOString()
    人.条数 = Number(人.条数 || 0) + 1
    脏 = true
    return 人
  }

  /**
   * 找人。**QQ 号优先，且只做精确匹配** —— 昵称只在「全库唯一」时才拿来兜底，
   * 撞名就返回 null（宁可让它问一句，也别认错人）。
   */
  function 找(谁) {
    const q = 清(谁, 40)
    if (!q) return null
    // ① QQ 号（唯一可信的身份）
    if (数据.人[q]) return 数据.人[q]
    // ② 昵称兜底：必须**恰好一个**匹配，撞名就不猜
    if (!/^\d+$/.test(q)) {
      const 命中 = Object.values(数据.人).filter((人) => 人.昵称 === q)
      if (命中.length === 1) return 命中[0]
    }
    return null
  }

  /** 给某人添一条印象。重复的不重复记。 */
  function 记(谁, 文本) {
    const 人 = 找(谁)
    if (!人) return { ok: false, 说: '群友簿里没有这个 QQ 号：' + 清(谁, 20) + '（等他先说句话就有了；昵称重名时也会找不到，用 QQ 号更准）' }
    const 文 = 清(文本, 印象字数)
    if (!文) return { ok: false, 说: '没写内容' }
    const 已有 = (人.印象 || []).find((x) => x.文本 === 文)
    if (已有) {
      已有.at = new Date().toISOString()
      已有.次 = Number(已有.次 || 1) + 1
      脏 = true
      return { ok: true, 说: '这条已经记过了（' + 人.昵称 + '），又提了一次' }
    }
    ;(人.印象 = 人.印象 || []).push({ 文本: 文, at: new Date().toISOString(), 次: 1 })
    if (人.印象.length > 印象上限) 人.印象 = 人.印象.slice(-印象上限)
    脏 = true
    return { ok: true, 说: '记下了：' + 人.昵称 + '（' + 人.号码 + '） —— ' + 文 }
  }

  /**
   * 给某人拼一段「注入用」的摘要。没什么可说的就返回空串。
   * 形如：`某某（123456789，聊过 42 次）：爱用「典」，说话很短`
   * ⚠ QQ 号必须带上 —— 模型照着它调 remember_person，昵称只是给人看的。
   */
  function 摘要(号码) {
    const 人 = 取人(号码)
    if (!人) return ''
    const 印象 = (人.印象 || []).slice(-注入条数).map((x) => x.文本).filter(Boolean)
    if (!印象.length) return ''
    const 次 = Number(人.条数 || 0)
    const 头 = 人.昵称 + '（' + 人.号码 + (次 >= 10 ? '，聊过 ' + 次 + ' 次' : '') + '）'
    return 头 + '：' + 印象.join('；')
  }

  /** 现在簿子里有几个人 */
  const 人数 = () => Object.keys(数据.人).length

  return { 见, 记, 找, 摘要, 取人, 人数, 刷, 文件,
           /** 仅供测试 / 排查：拿到原始数据 */
           原始: () => 数据 }
}
