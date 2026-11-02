# 合并上游更新

`vendor/dsh-qq-bridge` 是上游的本地分叉：**上游 1.5.0 + 本地补丁**。上游还在动，
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
# 0) 记下 base。第一次是 6731c022（1.1.2）；2026-11-02 合到 1.5.0 后是 1c85658。
#    以后每次合并完，把 base 更新成当时的 theirs。
BASE=1c85658
UP=/tmp/dsh-qq-bridge-new
WORK=/tmp/qqbridge-merge

# 1) 拿上游
rm -rf "$UP" && git clone https://github.com/Yuuyuko-uu/dsh-qq-link "$UP"   # 旧名 dsh-qq-bridge 会重定向

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
| 2026-11-02 | 1.4.2 (`93aa874`) → 1.5.0 (`1c85658`) | 10 处 | ① fs/path import 并集 ② 「抓歌名」+ 上游「按句拆」两个都留 ③ `落地一发` 形参加我们的 `引用id` + 上游的 `是本地手打`（调用处同步） ④ turn/start 注释用上游 ⑤ 触发/引用收尾 + 轮来源收尾并集 ⑥ 静默标记改用上游 1.4.8 的 `这轮静默`（我们那两条 + 一段死代码删掉） ⑦ 表情菜单留我们的 ⑧ `/receive` 精确路由 + 上游新 `/notice` 并集。**补丁 75 → 72**（少的三条都查过：两条上游正式修了同一个 bug、一条死代码） |

## 本地偏差：包名不跟上游改

上游 1.4.3 起把 npm 包名改成 `dsh-qq-link`，**我们保留 `dsh-qq-bridge`**。
原因：DSH 的 `dsh-client-modules` 校验 `package.json.name === loader specifier`，而本机
profile（`~/.dsh/profiles/web/package.json`）里那条依赖和 bundles 一直叫 `dsh-qq-bridge`。
改 profile 要同时动依赖 key、`pnpm-lock.yaml` 和 `node_modules` 软链，风险更大，没必要。
`cordis.patch.yml` 的 `name` 也保持 `dsh-qq-bridge`。路由前缀 `/dsh-qq-bridge` 和数据文件名
同理保持旧名（上游自己也是这么做的，改名会丢数据）。
**下次合并若在这几行冲突，按旧名保留。**

## 合并进来、但暂时关着的新能力

- **正文里的文件链接会真的上传文件**（1.4.5+）：上游接受任意绝对路径，只检查「存在 / 是
  文件 / ≤50MB」。**本地补丁已加 `文件根目录` 白名单**（`[本地补丁 2026-11-02]`：留空 =
  一个文件都不发；对 realpath 之后的真路径比前缀，防 `../` 和软链）。本机另外把 `发文件`
  设为 `false`。要开启：先填 `文件根目录`（逗号分隔），再打开 `发文件`。
- **`/notice` 路由**（1.5.0，收戳一戳的 HTTP 上报）：只认 `notice_type === 'poke'`，而
  NapCat 实际发的是 `notice_type: 'notify'` + `sub_type: 'poke'`；也没有 `target_id` /
  self 过滤和冷却。**保持 `收通知: false`，继续走 `tools/qq-events.py`**，等上游修。
- **管理接口只认本人**（1.5.0）：`/dsh-qq-bridge/state` 等本机 curl 会回
  `authentication_required`（设置页同源请求正常）；`/receive`、`/notice` 标了
  `{ 公开: true }`，不受影响。

## 合并之后的 base

下次合并，`BASE` 要换成**这次合进来的那个上游提交**（不是我们的提交）：

```bash
git -C /tmp/dsh-qq-bridge-new rev-parse main   # 合并当时的 theirs
```
