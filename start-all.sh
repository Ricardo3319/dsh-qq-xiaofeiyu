#!/usr/bin/env bash
#
# start-all.sh —— 「小肥鱼」QQ 陪聊栈的一键启停
#
#   ./start-all.sh                     拉起整套（= start）
#   ./start-all.sh start | up
#   ./start-all.sh stop  | down
#   ./start-all.sh status | st
#   ./start-all.sh url                 打出当前能打开的 DSH 网页地址（带 token）
#   ./start-all.sh check | ck          自检：人设模板 ↔ 本机、图库软链、图库索引
#   ./start-all.sh autostart off       关掉开机自启，以后手动跑本脚本
#   ./start-all.sh autostart on        恢复开机自启（下次登录生效）
#
# 为什么脚本不自己起进程，而是驱动 systemd 用户单元：
#   单元里攒着的都是踩出来的细节 —— NapCat 要等 niri 的 wayland socket
#   再起（Electron 必须有显示）、dsh-web 要带 Clash 代理环境、崩了要自己回来。
#   而且单元文件里写着真实 QQ 号（那只存在于部署侧）。这个仓库是公开的，
#   所以本文件只驱动单元名和端口，不出现任何号码。
#
set -uo pipefail

# 脚本自己所在的目录：自检要按仓库根去找 tools/ 和 sticker-packs
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

NAPCAT_UNIT=napcat.service
DSH_UNIT=dsh-web.service
EVENTS_UNIT=qq-events.service
SEARCH_UNIT=qq-search.service
UNITS=("$NAPCAT_UNIT" "$DSH_UNIT" "$EVENTS_UNIT" "$SEARCH_UNIT")

# 端口是用来判「真的活了」的 —— systemd 说 active 不等于服务能干活
# （NapCat 就是典型：进程在、端口没起，表现成「发消息不回复」）。
NAPCAT_PORT=3000
DSH_PORT=3080
EVENTS_PORT=3999
SEARCH_PORT=8888
MAGPIE_PORT=3425 # 模型网关，用户自己的单元，本脚本只检查不动它

# NapCat 的 --user-data-dir（见 ~/.local/bin/napcat-qq）。
# 同一时间只允许一个 QQ 实例写它，残留的旧实例会让 :3000 起不来。
QQ_DATA_DIR="$HOME/.config/napcat-qq-plugin"

BRIDGE_LOG="$HOME/.dsh/qq-bridge.log"

if [ -t 1 ]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_BAD=$'\033[31m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
    C_OK=; C_WARN=; C_BAD=; C_BOLD=; C_OFF=
fi
ok()   { printf '  %s✓%s %s\n' "$C_OK" "$C_OFF" "$*"; }
warn() { printf '  %s!%s %s\n' "$C_WARN" "$C_OFF" "$*"; }
bad()  { printf '  %s✗%s %s\n' "$C_BAD" "$C_OFF" "$*"; }
step() { printf '\n%s%s%s\n' "$C_BOLD" "$*" "$C_OFF"; }

usage() {
    sed -n '3,12p' "$0" | sed 's/^#\{0,1\} \{0,1\}//'
}

# ---- 基础设施 ----------------------------------------------------------

require_session() {
    if [ -z "${XDG_RUNTIME_DIR:-}" ] || ! systemctl --user show-environment >/dev/null 2>&1; then
        bad "连不上 systemd 用户管理器 —— 这个脚本要在图形会话的终端里跑"
        exit 1
    fi
}

# 纯 TCP 探测：连上就算活（dsh-web 的 / 会回 401，那也是活着）
port_up() { timeout 2 bash -c "exec 3<>/dev/tcp/127.0.0.1/$1" 2>/dev/null; }

wait_port() { # 名字 端口 超时秒
    local name=$1 port=$2 t=${3:-60} i=0
    while [ "$i" -lt $((t * 2)) ]; do
        if port_up "$port"; then ok "$name 已就绪（:$port）"; return 0; fi
        sleep 0.5; i=$((i + 1))
    done
    bad "$name ${t}s 内没起来（:$port 不通）"
    return 1
}

start_one() { # 单元 名字 端口 超时秒
    local unit=$1 name=$2 port=$3 t=$4
    if systemctl --user is-active --quiet "$unit"; then
        if port_up "$port"; then ok "$name 本来就在跑（:$port）"; return 0; fi
        warn "$name 的单元是 active 但 :$port 不通 → 重启一次"
        systemctl --user restart "$unit" || { bad "$name 重启失败"; return 1; }
    else
        systemctl --user start "$unit" || { bad "$name 启动失败"; return 1; }
    fi
    wait_port "$name" "$port" "$t"
}

clean_stale_qq() {
    systemctl --user is-active --quiet "$NAPCAT_UNIT" && return 0
    if pgrep -f "user-data-dir=$QQ_DATA_DIR" >/dev/null 2>&1; then
        warn "单位外还有 QQ 实例占着同一个 user-data-dir（会抢 :$NAPCAT_PORT）→ 清掉"
        pkill -f "user-data-dir=$QQ_DATA_DIR" 2>/dev/null
        sleep 3
    fi
}

# dsh web 每次启动都重新随机生成 token，浏览器里那条 30 天 cookie 绑的是上一次的。
# 所以重启之后旧的地址/书签一律 401，表现成「网页打不开」。当前这条只写在 journal 里。
dsh_url() {
    journalctl --user -u "$DSH_UNIT" --no-pager -n 400 2>/dev/null |
        grep -o "http://127\.0\.0\.1:$DSH_PORT/?token=[^[:space:]]*" | tail -1
}

# ---- 子命令 ------------------------------------------------------------

cmd_start() {
    local rc=0

    step "① NapCat（QQ 协议端，起得最慢）"
    clean_stale_qq
    start_one "$NAPCAT_UNIT" NapCat "$NAPCAT_PORT" 90 || rc=1

    step "② DSH web（桥的宿主）"
    start_one "$DSH_UNIT" "DSH web" "$DSH_PORT" 60 || rc=1
    if port_up "$MAGPIE_PORT"; then
        ok "magpie 在跑（:$MAGPIE_PORT）"
    else
        warn "magpie（:$MAGPIE_PORT）没起来 —— dsh-web 的 Wants= 本该拉它，起不来去看 systemctl --user status magpie"
    fi

    step "③ 事件适配器（戳一戳 → 桥）"
    start_one "$EVENTS_UNIT" "事件适配器" "$EVENTS_PORT" 20 || rc=1

    step "④ 本地搜索（SearXNG）"
    start_one "$SEARCH_UNIT" "本地搜索" "$SEARCH_PORT" 60 || rc=1

    step "结果"
    if [ "$rc" -eq 0 ]; then
        echo "  四个都在跑。还剩一步只能手动做："
        local url
        url=$(dsh_url)
        if [ -n "$url" ]; then
            echo "  用这条打开（端口直连会 401，token 每次启动都变）："
            echo
            echo "    $url"
            echo
        else
            echo "  打开 http://127.0.0.1:$DSH_PORT （journal 里还没打出 token，用 ./start-all.sh url 再取）"
        fi
        echo "  然后把私聊 + 各个群的会话点开。"
        echo "  DSH 一重启，会话就是关的 —— 桥投递不进去，只会在日志里每 2 秒重试一次，"
        echo "  而且超过 10 分钟的旧消息按设计不再补投。"
    else
        echo "  上面标 ✗ 的那几条先看；单元日志：systemctl --user status <单元>"
    fi
    echo
    echo "  收发记录：tail -f $BRIDGE_LOG"
}

cmd_stop() {
    step "停止（顺序：本地搜索 → 事件适配器 → DSH web → NapCat）"
    systemctl --user stop "$SEARCH_UNIT" "$EVENTS_UNIT" "$DSH_UNIT" "$NAPCAT_UNIT" 2>/dev/null
    sleep 1

    if pgrep -f "user-data-dir=$QQ_DATA_DIR" >/dev/null 2>&1; then
        warn "还有 QQ 进程没退（多半是手工起的那个）→ 清掉"
        pkill -f "user-data-dir=$QQ_DATA_DIR" 2>/dev/null
        sleep 2
    fi

    local u
    for u in "$SEARCH_UNIT" "$EVENTS_UNIT" "$DSH_UNIT" "$NAPCAT_UNIT"; do
        if systemctl --user is-active --quiet "$u"; then bad "$u 还活着"; else ok "$u 已停"; fi
    done
    echo
    echo "  magpie 没动 —— 那不是这套的，别的客户端也在用。"
}

cmd_status() {
    # 第一列只用 ASCII —— printf 按字符数补宽度，中日韩字会被撑歪
    printf '  %-10s %-9s %-6s %s\n' UNIT SYSTEMD PORT 说明
    local unit name port label state note
    while read -r unit name port label; do
        if systemctl --user is-active --quiet "$unit"; then state=active; else state=inactive; fi
        if port_up "$port"; then note=通; else note=不通; fi
        printf '  %-10s %-9s %-6s %s %s\n' "$name" "$state" ":$port" "$note" "$label"
    done <<EOF
$NAPCAT_UNIT napcat $NAPCAT_PORT QQ协议端
$DSH_UNIT dsh-web $DSH_PORT 桥的宿主
$EVENTS_UNIT qq-events $EVENTS_PORT 戳一戳适配器
$SEARCH_UNIT qq-search $SEARCH_PORT 本地搜索
EOF

    if port_up "$MAGPIE_PORT"; then note=通; else note=不通; fi
    printf '  %-10s %-9s %-6s %s %s\n' magpie - ":$MAGPIE_PORT" "$note" "模型网关（你的单元，不碰）"

    echo
    printf '  开机自启：'
    for unit in "${UNITS[@]}"; do printf '%s=%s ' "${unit%.service}" "$(systemctl --user is-enabled "$unit" 2>&1)"; done
    echo
    if [ -f "$BRIDGE_LOG" ]; then
        echo "  桥日志最后一行：$(tail -1 "$BRIDGE_LOG")"
    fi
}

cmd_url() {
    local url
    url=$(dsh_url)
    if [ -n "$url" ]; then
        echo "$url"
        echo
        echo "  （token 每次启动 dsh-web 都会换，换过之后旧的地址和书签就失效了）" >&2
        return 0
    fi
    if ! systemctl --user is-active --quiet "$DSH_UNIT"; then
        bad "dsh-web 没在跑 —— 先 ./start-all.sh"
        return 1
    fi
    bad "journal 里还没出现带 token 的地址，等几秒再试；或在网页里重新打开一次"
    return 1
}

cmd_check() {
    # 自检：不碰进程，只核对「仓库里的东西」和「本机在跑的那份」有没有走散。
    # 这三样都是改了本机却忘了同步回仓库、或者换了机器没重建时会静默失效的东西。
    local fail=0
    echo "人设模板 ↔ 本机 profile："
    if python3 -I "$HERE/tools/persona_templates.py" --check; then :; else fail=1; fi
    echo
    echo "图库："
    if [ -d "$HERE/sticker-packs" ]; then
        ok "sticker-packs 软链在（$(readlink -f "$HERE/sticker-packs" 2>/dev/null)）"
    else
        bad "没有 sticker-packs 软链 —— 跑：ln -s \"\$HOME/.dsh/meme-packs\" \"$HERE/sticker-packs\""; fail=1
    fi
    local idx="$HOME/.dsh/qq-sticker-packs.json"
    if [ -f "$idx" ]; then
        ok "图库索引在：$(python3 -I -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["图"]),"张")' "$idx" 2>/dev/null)"
        echo "  （装了新图库要重跑：python3 tools/sticker_packs_index.py）"
    else
        bad "没有图库索引 —— 跑：python3 tools/sticker_packs_index.py"; fail=1
    fi
    echo
    echo "现做表情（meme-generator）："
    local meme_py="$HOME/.dsh/qq-meme/.venv/bin/python"
    if [ -x "$meme_py" ] && "$meme_py" -I -c 'import meme_generator' >/dev/null 2>&1; then
        ok "meme-generator 环境在（qq_meme 用这个，不是另一个机器人）"
    else
        bad "没有 ~/.dsh/qq-meme —— 装法在 README「现做表情」。静图菜单不受影响"; fail=1
    fi
    echo
    [ "$fail" = 0 ] && ok "自检通过" || bad "上面有没对上的，按提示处理"
    return "$fail"
}

cmd_autostart() {
    case "${1:-}" in
        off)
            systemctl --user disable "${UNITS[@]}" && ok "三个单元的开机自启都关了（下次登录不会自己起）"
            echo "  以后要用了就跑：$(basename "$0")"
            ;;
        on)
            systemctl --user enable "${UNITS[@]}" && ok "三个单元的开机自启恢复了（下次登录生效）"
            ;;
        *)
            echo "用法：$(basename "$0") autostart on|off"
            echo "当前状态："
            local u
            for u in "${UNITS[@]}"; do printf '  %-20s %s\n' "$u" "$(systemctl --user is-enabled "$u" 2>&1)"; done
            [ -n "${1:-}" ] && return 1 || return 0
            ;;
    esac
}

# ---- 入口 --------------------------------------------------------------

case "${1:-start}" in
    start | up | "")  require_session; cmd_start ;;
    stop | down)      require_session; cmd_stop ;;
    status | st)      require_session; cmd_status ;;
    url)              require_session; cmd_url ;;
    check | ck)       cmd_check ;;                          # 自检不碰进程，登录会话没起也能跑
    autostart)        require_session; shift; cmd_autostart "${1:-}" ;;
    -h | --help | help) usage ;;
    *)
        bad "不认识的子命令：$1"
        echo
        usage
        exit 2
        ;;
esac
