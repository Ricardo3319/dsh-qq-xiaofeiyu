# 合并上游更新

`vendor/dsh-qq-bridge` 是上游的本地分叉：**上游 1.4.2 + 本地补丁**。上游还在动，
所以要能反复合并。这份记的是**怎么做**，以及**踩过的坑**。

## 为什么不用 `git pull`

`vendor/` 不是上游的克隆（没有 `.git`），而且改过的地方和上游改过的地方会撞。
直接覆盖会丢补丁，直接 pull 又没依据。正确做法是**三方合并**：

```
base   = 上游某个提交（我们上次对齐的那个）
ours   = vendor/ 现在的样子（base + 本地补丁）
theirs = 上游 main
```

## 步骤

```bash
# 0) 记下 base。第一次是 6731c022（1.1.2）。以后每次合并完，把 base 更新成当时的 theirs。
BASE=6731c022
UP=/tmp/dsh-qq-bridge-new
WORK=/tmp/qqbridge-merge

# 1) 拿上游
rm -rf "$UP" && git clone --depth 50 https://github.com/Yuuyuko-uu/dsh-qq-bridge "$UP"

# 2) 建临时仓：base 之上，放我们的样子
rm -rf "$WORK" && cp -a "$UP" "$WORK" && cd "$WORK"
git checkout -q -B merge-base "$BASE"
git checkout -q -b local-patches
rsync -a --delete --exclude '.git' ~/agents/QQ_ds/vendor/dsh-qq-bridge/ ./
# ⚠ 坑 1：我们没把上游的 tests/ 拷进 vendor，rsync --delete 会把它删掉，
#   于是「我们删了测试」会跟「上游改了测试」撞。把它按 base 恢复回来：
git checkout merge-base -- tests/ 2>/dev/null || true
git add -A && git commit -q -m "本地补丁"

# 3) 合并
git -c user.email=x -c user.name=x merge main
# 冲突只会出现在 lib/host.js —— 其余（client.js / package.json / README / tests）自动合
```

## 解冲突的规矩

**默认：两边都要。** 上游加的功能和我们的补丁通常是正交的，冲突多半是「改到同一行」。

| 冲突形状 | 怎么合 |
|---|---|
| import 行各加各的 | 并集 |
| 同一个入口各加一次调用（心跳之类） | 全都调 |
| 上游改了同一段逻辑，我们改的是它的**条件** | 以上游的新结构为准，把我们的条件/参数套进去 |
| 上游**正式修了**我们本地也修过的 bug | 用上游那版，删掉我们的（本地那份是临时补的） |

合完检查：

```bash
grep -c '\[本地补丁' lib/host.js      # 对比合之前的数量，少了就说明有补丁被吞
node --check lib/host.js
```

## 验证（必须跑）

```bash
node tests/宿主半边.mjs
node tests/网页半边.mjs
node tests/inbound-batching.mjs
node tests/inbound-lifecycle.mjs
node tests/inbound-singleflight.mjs
```

上游的测试**不覆盖我们的补丁**（群友簿 / 表情库 / 共同记忆 / 热度），所以它们全过
只说明「没把上游弄坏」。合完还要实机看一眼：重启 DSH，确认工具都挂上了：

```bash
systemctl --user restart dsh-web.service
grep '工具已挂上' ~/.dsh/qq-bridge.log | tail
```

## 装回去

```bash
tar czf /tmp/vendor-$(date +%Y%m%d).tar.gz -C ~/agents/QQ_ds/vendor dsh-qq-bridge   # 先备份
rsync -a --delete --exclude '.git' --exclude 'node_modules' /tmp/qqbridge-merge/ ~/agents/QQ_ds/vendor/dsh-qq-bridge/
cd ~/agents/QQ_ds && git add -A && git commit -m "合并上游 <版本>"
```

## 已经合过的记录

| 日期 | 从 → 到 | 冲突 | 备注 |
|---|---|---|---|
| 2026-10-30 | 1.1.2 (`6731c022`) → 1.4.2 | 4 处 | ① fs import 并集 ② 收消息入口三个心跳都调 ③ 群聊节奏：一律排队 + 热度放宽 ④ 自己号 → 改用上游 `拿自己QQ`，删掉本地那版 |

## 还没合的：1.4.3（`d5a034c`）

**有实质代码改动，不是只改许可**，其中一条是安全相关的：

- **「只听点名」对群里所有人生效** —— 去掉了「自己发的话绕过过滤」的捷径。
  我们本地也有一条同目的的补丁（跳过机器人自己发的消息），合并时要看清谁覆盖谁。
- 每行新增「不受点名限制的 QQ」名单。
- 长回复可选按句子拆（默认关；括号里的标点不算断句）。
- 人设三处：2000 字上限放宽到 2 万字、跟着心跳补挂（重启后定时任务触发的回合也有人设）、
  缓存认 agent 实例。**「跟着心跳补挂」跟我们那条「投递前补挂工具」是同一类问题的两种解法**，
  合并时要挑一个。

合的时候按上面流程走，`BASE` 用 `6731c022`（上次对齐的点不变）。

## 合并之后的 base

下次合并，`BASE` 要换成**这次合进来的那个上游提交**（不是我们的提交）：

```bash
git -C /tmp/dsh-qq-bridge-new rev-parse main   # 合并当时的 theirs
```
