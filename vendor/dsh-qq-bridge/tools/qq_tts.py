#!/usr/bin/env python3
"""文字 → 语音文件（edge-tts）。给 dsh-qq-bridge 出站语音（qq_voice 工具）用。

约定跟 asr_cli.py 反过来：**文字从 stdin 读**，音频写到 --out。
用 stdin 而不是命令行参数，是为了不跟引号 / 空格 / 表情符号较劲 ——
桥那边直接 spawn(解释器, [脚本, '--out', 路径]) 并写 stdin，不过 shell。

用法：
    /path/to/python qq_tts.py --out /path/to/x.mp3 [--voice zh-CN-XiaoyiNeural]

退出码：
    0  → 写好了
    非 0 → stderr 里是原因（桥会把它带进日志）
"""
import argparse
import asyncio
import sys


def 洗文本(s: str) -> str:
    # edge-tts 对着 SSML 说话，& < > 会炸；换行也念不顺，压成空格。
    s = str(s or '')
    for a, b in (('&', '和'), ('<', '《'), ('>', '》')):
        s = s.replace(a, b)
    return ' '.join(s.split()).strip()


async def 合成(文本: str, 出: str, 音色: str, 语速: str, 音调: str, 音量: str) -> None:
    import edge_tts
    c = edge_tts.Communicate(文本, 音色, rate=语速, pitch=音调, volume=音量)
    await c.save(出)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True, help='输出的音频文件（mp3）')
    ap.add_argument('--voice', default='zh-CN-XiaoyiNeural')
    ap.add_argument('--rate', default='+0%')
    ap.add_argument('--pitch', default='+0Hz')
    ap.add_argument('--volume', default='+0%')
    ap.add_argument('--max-chars', type=int, default=300, help='太长就截断（语音条不该是一篇文章）')
    a = ap.parse_args()

    文本 = 洗文本(sys.stdin.read())
    if not 文本:
        sys.stderr.write('没有从 stdin 读到文字\n')
        return 2
    if len(文本) > a.max_chars:
        文本 = 文本[: a.max_chars]
        sys.stderr.write('文本过长，已截到 %d 字\n' % a.max_chars)

    try:
        asyncio.run(合成(文本, a.out, a.voice, a.rate, a.pitch, a.volume))
    except Exception as e:  # noqa: BLE001 —— 网络/服务端什么错都要原样带回去
        sys.stderr.write('%s: %s\n' % (type(e).__name__, e))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
