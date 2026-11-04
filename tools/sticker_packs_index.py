#!/usr/bin/env python3
"""把 ~/.dsh/meme-packs 里装好的图库编成一份索引，给桥往 QQ 里发用。

为什么要有这一步：图库包是 dsh-meme 的东西（网页面板 / send_meme），
QQ 这条路上桥只认「相对路径的图片文件」；模型又不可能记住 330 个文件名。
所以桥每轮从这份索引里随机抽几张塞进表情菜单 —— 抽到的那几张它才知道能发。

用法：
    python3 tools/sticker_packs_index.py            # 扫 ~/.dsh/meme-packs，重写索引
    python3 tools/sticker_packs_index.py --dir DIR  # 扫别的目录

输出：~/.dsh/qq-sticker-packs.json
     {"图": [{"相对": "sticker-packs/<包>/memes/<tag>/<文件>", "别号": "p1234",
            "情绪": "...", "包": "..."}]}

别号是给模型抄的短名字：菜单里只给 `p1234`，桥按别号翻回整条路径（5 个字符，抄不错）。

⚠ 相对路径里的 `sticker-packs/` 是仓库根目录下的一个软链，指向 ~/.dsh/meme-packs，
   这样桥按「图片根目录」（默认就是仓库根）就能找到图，不用改配置。
   软链不在 git 里（.gitignore 已排除），重建环境时 `ln -s ~/.dsh/meme-packs sticker-packs`。
"""
import argparse
import json
import os
import sys
import time
import zlib

IMG = ('.png', '.jpg', '.jpeg', '.gif', '.webp')

# 图库里的标签是英文目录名，换成她看得懂的情绪词。
#
# [本地补丁 2026-11-04] 原来这里全是**一个词**（`fool: 拒绝`、`happy: 开心`），
#   而她自己收的那批在图库菜单里带的是整句（「吐槽对方画饼/空口承诺的时候」）。
#   实测效果是：菜单同时给 21 张 `收_*` + 8 张图库，她几乎只挑 `收_*` —— 单看标签，
#   图库那几张根本不像「为此刻准备的」。现在改成同样的口吻，一个标签一句话。
#   顺手改了 `fool`：它一直是「拒绝」，其实英文是「犯傻 / 装蠢」，标错了会挑错图。
情绪 = {
    'angry': '生气/被惹毛，想怼回去的时候',
    'happy': '开心/被逗乐，笑得停不下来的时候',
    'sad': '难过/委屈，想被哄的时候',
    'shy': '害羞/被夸得不好意思的时候',
    'confused': '疑惑/听不懂对方在说什么的时候',
    'surprised': '吃惊/被吓一跳的时候',
    'like': '喜欢/比心，对人有好感的时候',
    'love': '喜欢/比心，对人有好感的时候',
    'sleep': '困了/想睡觉、懒得动的时候',
    'morning': '早安/刚醒打招呼的时候',
    'work': '干活/摸鱼、加班没劲的时候',
    'sigh': '无语/看不下去、懒得理的时候',
    'see': '看见了/围观、惊了的时候',
    'daily': '日常/随口应一声的时候',
    'baka': '嫌弃/骂人笨蛋的时候',
    'fool': '犯傻/装傻卖蠢的时候',
    'color': '花痴/看帅哥美女犯花痴的时候',
    'cpu': '脑子烧了/想不明白的时候',
    'givemoney': '要钱/讨零食、撒娇的时候',
    'meow': '卖萌/耍可爱的时候',
    'cry': '哭/委屈得要哭的时候',
    'laugh': '大笑/起哄、看热闹的时候',
    'eat': '干饭/饿了想吃东西的时候',
    'drink': '喝/干杯、来一杯的时候',
    'hello': '打招呼/有人来了的时候',
    'bye': '告别/要走的时候',
    'think': '思考/琢磨对方什么意思的时候',
    'cool': '酷/装酷耍帅的时候',
    'reply': '回应/搭话接一句的时候',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default=os.path.expanduser('~/.dsh/meme-packs'))
    ap.add_argument('--out', default=os.path.expanduser('~/.dsh/qq-sticker-packs.json'))
    a = ap.parse_args()

    if not os.path.isdir(a.dir):
        print(f'没有图库目录：{a.dir}', file=sys.stderr)
        return 1

    图们 = []
    用过的 = {}

    def 取别号(相对):
        """p + 4 位数字，按路径做 crc，重复就往后挪 —— 同一张图每次生成的别号稳定。"""
        n = zlib.crc32(相对.encode('utf-8')) % 10000
        for _ in range(10000):
            号 = 'p%04d' % n
            if 号 not in 用过的:
                用过的[号] = 相对
                return 号
            n = (n + 1) % 10000
        raise SystemExit('别号用完了')

    for 包 in sorted(os.listdir(a.dir)):
        根 = os.path.join(a.dir, 包, 'memes')
        if not os.path.isdir(根):
            continue
        for 标签 in sorted(os.listdir(根)):
            目录 = os.path.join(根, 标签)
            if not os.path.isdir(目录):
                continue
            for 文件 in sorted(os.listdir(目录)):
                if not 文件.lower().endswith(IMG):
                    continue
                相对 = f'sticker-packs/{包}/memes/{标签}/{文件}'
                图们.append({
                    '相对': 相对,
                    '别号': 取别号(相对),
                    '情绪': 情绪.get(标签.lower(), 标签),
                    '包': 包,
                })

    出 = {'生成时间': time.strftime('%Y-%m-%d %H:%M'), '目录': a.dir, '图': 图们}
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(出, f, ensure_ascii=False, indent=1)

    from collections import Counter
    print(f'索引写好：{a.out}')
    print(f'共 {len(图们)} 张，来自 {len(set(x["包"] for x in 图们))} 个包')
    for 包, 数 in Counter(x['包'] for x in 图们).most_common():
        print(f'  {包:22} {数:>4} 张')
    return 0


if __name__ == '__main__':
    sys.exit(main())
