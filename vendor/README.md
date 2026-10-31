# vendor/ —— 本地副本的插件

这里放**从上游拷下来、再由我们改过的**插件副本。profile 用 `link:` 依赖指过来，
所以**这个目录里的文件就是正在跑的代码**（改完重启 DSH 即生效）。

为什么要这么做：这些插件装在 `~/.dsh/profiles/web/node_modules/` 下，是包管理器管的目录 ——
直接改会被 `dsh plugin` 更新覆盖，也容易被权限拦截。放到自己目录里就没有这些问题。

---

## dsh-qq-bridge

| | |
|---|---|
| 上游 | https://github.com/Yuuyuko-uu/dsh-qq-bridge |
| 拷下来的版本 | **1.1.2** |
| 上游提交 | `6731c02295492f54b39e2617ed8c2292eb11bfd1` |
| 拷贝日期 | 2026-10-28 |
| profile 里的依赖 | `link:/home/ricardo/agents/QQ_ds/vendor/dsh-qq-bridge` |

### 我们改了哪里

只有一处，在 `lib/host.js` 的 `/receive` 路由里，代码里带 `[本地补丁 2026-10-28]` 注释：

**让 `/receive` 认 `{类型, 号码}`，按「绑定」精确路由。**

为什么需要：「戳一戳」是 OneBot 的 `notice` 事件，**不进消息历史**，而桥是靠轮询消息历史收消息的 ——
所以桥自己永远看不见戳。只能由外部程序 `~/agents/QQ_ds/tools/qq-events.py` 把戳转成文字、POST 给 `/receive`。
但上游 1.1.2 的 `/receive` 只接受 `text`，会落到**第一条绑定**（私聊）—— 群里的戳会被投错屋子。
补丁加上 `类型` + `号码` 后按绑定找对那一行，并把 `点名` 置为 true（戳本来就是冲它来的，
让它绕过回复门槛和群聊节奏）。

不传这两个字段时，行为跟上游完全一样。

### 上游更新了怎么办

```bash
cd /tmp && rm -rf dsh-qq-bridge-new
git clone --depth 1 https://github.com/Yuuyuko-uu/dsh-qq-bridge dsh-qq-bridge-new

# 看清楚新版改了什么（尤其 /receive 有没有自己加上路由能力 —— 有的话我们的补丁就可以去掉）
diff -u ~/agents/QQ_ds/vendor/dsh-qq-bridge/lib/host.js /tmp/dsh-qq-bridge-new/lib/host.js | head -100

# 备份旧的，拷新的过来（保留 .git 之外的都要）
cp -a ~/agents/QQ_ds/vendor/dsh-qq-bridge /tmp/dsh-qq-bridge.bak-$(date +%F)
rsync -a --delete --exclude='.git/' /tmp/dsh-qq-bridge-new/ ~/agents/QQ_ds/vendor/dsh-qq-bridge/

# 然后按上面的说明把 /receive 那个补丁重新打一遍（搜「本地补丁 2026-10-28」对照旧备份）
# 最后重启
systemctl --user restart dsh-web.service
```

⚠ **设置不会丢**：配置存在 `~/.dsh/qq-bridge-config.json`，跟代码无关。
