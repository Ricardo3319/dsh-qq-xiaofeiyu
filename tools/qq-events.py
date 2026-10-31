#!/usr/bin/env python3
"""
QQ 事件 → DSH 桥 适配器

为什么需要它：
  dsh-qq-bridge 是「每 2 秒轮询一次消息历史」，而「戳一戳」是 OneBot 的
  notice 事件，根本不进消息历史 —— 所以桥永远看不到，表现为「戳了没反应」。

做法：
  NapCat 开一个 HTTP 客户端，把事件 POST 到本服务 → 本服务挑出「戳一戳」
  → 变成一句文字 → POST 给 dsh-qq-bridge 的 /receive → 桥照常叫醒对应会话。

  ⚠ NapCat 的上报走 chunked 编码，必须手工拆块（BaseHTTPRequestHandler 不认）。

  ⚠ 桥的 /receive 原本不带来源聊天（会落到第一条绑定）。已给 dsh-qq-bridge
    打本地补丁，允许带上 {类型, 号码} 精确路由；万一补丁被更新覆盖，这两个
    字段会被忽略、退回「进私聊」，不会报错。

用法：
  python3 qq-events.py
  nohup python3 qq-events.py > /tmp/qq-events.log 2>&1 &
"""

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- 配置 ----
# ⚠ 这些号都从环境变量来，代码里不留真实值（这个文件会进公开仓库）。
#   部署时写进 systemd 单元或 shell，见 README。
NAPCAT = os.environ.get("NAPCAT", "http://127.0.0.1:3000")
DSH_RECEIVE = os.environ.get("DSH_RECEIVE", "http://127.0.0.1:3080/dsh-qq-bridge/receive")
PRIVATE_QQ = os.environ.get("PRIVATE_QQ", "")
# [本地补丁 2026-10-30] 机器人自己的 QQ 号。优先用事件里的 self_id；
#   事件里没有时拿它兜底（判「这戳是不是冲我来的」要用）。
BOT_QQ = os.environ.get("BOT_QQ", "")
GROUPS = set(x.strip() for x in os.environ.get("GROUPS", "").split(",") if x.strip())
LISTEN = ("127.0.0.1", int(os.environ.get("PORT", "3999")))

DEBOUNCE_SEC = 8          # 同一个人在同一个聊天里，这么久内只转一次
BRIDGE_CONFIG = os.path.expanduser(os.environ.get("BRIDGE_CONFIG", "~/.dsh/qq-bridge-config.json"))
_last = {}
_dumped = False
_names = {}
_bind_cache = (0.0, set(), set())


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def 绑定群与私聊():
    """桥里已经绑了会话的群号和私聊号。

    为什么不只信环境变量 GROUPS：这份名单和桥的「绑定」本来是同一件事，分两处
    维护就会走散 —— 2026-10-29 桥里加了一个新群，这里还是老的两个号，
    那个群里的戳全被当成「未绑定」丢掉，表现就是戳了没反应。
    现在跟着桥的配置走，环境变量只当兜底（读不到配置时仍然能用）。
    """
    global _bind_cache
    now = time.time()
    if now - _bind_cache[0] < 60:
        return _bind_cache[1], _bind_cache[2]
    groups, privates = set(GROUPS), {PRIVATE_QQ}
    try:
        with open(BRIDGE_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        for b in (cfg.get("绑定") or []):
            num = str(b.get("号码") or "")
            if not num:
                continue
            if b.get("类型") == "群":
                groups.add(num)
            elif b.get("类型") == "私聊":
                privates.add(num)
    except Exception as e:
        log("读桥配置失败，只用环境变量里的名单: %s" % e)
    _bind_cache = (now, groups, privates)
    return groups, privates


def napcat(action, payload=None):
    body = json.dumps(payload or {}, ensure_ascii=False).encode()
    req = urllib.request.Request(NAPCAT + "/" + action, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read() or b"{}")
    except Exception as e:
        log("napcat %s 失败: %s" % (action, e))
        return {}


def nickname_of(uid):
    uid = str(uid)
    if uid in _names:
        return _names[uid]
    name = uid
    for f in (napcat("get_friend_list").get("data") or []):
        if str(f.get("user_id")) == uid:
            name = f.get("nickname") or uid
            break
    _names[uid] = name
    return name


def forward(text, target):
    payload = {"text": text}
    payload.update(target)
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(DSH_RECEIVE, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return "转发失败: %s" % e


def read_body(handler):
    """读请求体：chunked 或 Content-Length 两种。"""
    te = (handler.headers.get("Transfer-Encoding") or "").lower()
    if "chunked" in te:
        parts = []
        while True:
            line = handler.rfile.readline().strip()
            if not line:
                continue
            size = int(line.split(b";")[0], 16)
            if size == 0:
                handler.rfile.readline()
                break
            parts.append(handler.rfile.read(size))
            handler.rfile.read(2)
        return b"".join(parts)
    n = int(handler.headers.get("Content-Length") or 0)
    return handler.rfile.read(n) if n else b""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        global _dumped
        raw = b""
        try:
            raw = read_body(self)
            ev = json.loads(raw or b"{}")
            if not isinstance(ev, dict):
                ev = {}
        except Exception as ex:
            log("解析失败: %s" % ex)
            ev = {}

        if not _dumped:
            _dumped = True
            log("首个上报 ctype=%s te=%s raw=%r"
                % (self.headers.get("Content-Type"),
                   self.headers.get("Transfer-Encoding"), raw[:200]))

        out = {"ok": True}

        if ev.get("post_type") == "notice" and ev.get("sub_type") == "poke":
            gid = ev.get("group_id")
            uid = ev.get("user_id")
            # [本地补丁 2026-10-30] 戳一戳是**双向**事件：别人戳她、她戳别人，NapCat 发的是
            #   两条长得一模一样的 notice。以前只看 sub_type，于是**她戳回去的那一下被当成
            #   「有人戳我」又灌回桥里** —— 她看见了再戳回去，再灌回来，能对着戳个没完。
            #   现在两头都卡：戳的人不能是我自己，被戳的必须是我。
            tid = ev.get("target_id")
            自己 = str(ev.get("self_id") or BOT_QQ or "")
            冲我来的 = True
            if 自己 and str(uid) == 自己:
                log("跳过：这是我自己戳出去的（戳了 %s）" % tid)
                冲我来的 = False
            elif 自己 and tid is not None and str(tid) != 自己:
                log("跳过：这戳不是冲我来的（%s 戳了 %s）" % (uid, tid))
                冲我来的 = False
            key = ("g" + str(gid)) if gid else ("p" + str(uid))
            groups, privates = 绑定群与私聊()
            if not 冲我来的:
                pass                                   # 上面已经记过日志了，没事可做
            elif time.time() - _last.get(key, 0) < DEBOUNCE_SEC:
                log("戳（冷却中）%s" % key)
            elif gid and str(gid) in groups:
                _last[key] = time.time()
                who = nickname_of(uid)
                log("群戳 %s（%s）→ 转发" % (gid, who))
                # [本地补丁 2026-10-30] 带上对方的 QQ 号 —— 「戳回去」(qq_poke) 和点赞都要靠它认人，
                #   只给昵称的话模型没法调（昵称会改、也可能重名）。
                out["forwarded"] = forward("【戳一戳】%s（%s）戳了你一下，想戳回去就用 qq_poke"
                                           % (who, uid),
                                           {"类型": "群", "号码": str(gid)})
            elif not gid and str(uid) in privates:
                _last[key] = time.time()
                who = nickname_of(uid)
                log("私聊戳（%s）→ 转发" % who)
                out["forwarded"] = forward("【戳一戳】%s（%s）戳了你一下，想戳回去就用 qq_poke"
                                           % (who, uid),
                                           {"类型": "私聊", "号码": str(uid)})
            else:
                log("跳过未绑定的戳 group=%s user=%s" % (gid, uid))

        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        data = b'{"ok":true,"service":"qq-events"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    log("qq-events 监听 %s:%d | 自己 %s | 私聊 %s | 群 %s | DSH %s"
        % (LISTEN[0], LISTEN[1], BOT_QQ or "（没配！自己戳自己拦不住）", PRIVATE_QQ or "（没配）",
           ",".join(sorted(GROUPS)) or "（没配）", DSH_RECEIVE))
    ThreadingHTTPServer(LISTEN, Handler).serve_forever()
