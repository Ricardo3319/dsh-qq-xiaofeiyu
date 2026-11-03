#!/usr/bin/env python3
"""把 ~/.dsh/meme-packs 里装好的图库编成一份索引，给桥往 QQ 里发用。

为什么要有这一步：图库包是 dsh-meme 的东西（网页面板 / send_meme），
QQ 这条路上桥只认「相对路径的图片文件」；模型又不可能记住 330 个文件名。
所以桥每轮从这份索引里随机抽几张塞进表情菜单 —— 抽到的那几张它才知道能发。

用法：
    python3 tools/sticker_packs_index.py            # 扫 ~/.dsh/meme-packs，重写索引
    python3 tools/sticker_packs_index.py --dir DIR  # 扫别的目录

输出：~/.dsh/qq-sticker-packs.json
     {"图": [{"相对": "sticker-packs/<包>/memes/<tag>/<文件>", "情绪": "...", "包": "..."}]}

⚠ 相对路径里的 `sticker-packs/` 是仓库根目录下的一个软链，指向 ~/.dsh/meme-packs，
   这样桥按「图片根目录」（默认就是仓库根）就能找到图，不用改配置。
   软链不在 git 里（.gitignore 已排除），重建环境时 `ln -s ~/.dsh/meme-packs sticker-packs`。
"""
import argparse
import json
import os
import sys
import time

IMG = ('.png', '.jpg', '.jpeg', '.gif', '.webp')

# 图库里的标签是英文目录名，换成她看得懂的情绪词
情绪 = {
    'angry': '生气', 'happy': '开心', 'sad': '难过', 'shy': '害羞',
    'confused': '疑惑', 'surprised': '惊讶', 'like': '喜欢', 'sleep': '睡觉',
    'morning': '早安', 'work': '摸鱼', 'sigh': '无语', 'see': '惊了',
    'daily': '日常', 'baka': '嫌弃', 'fool': '拒绝', 'color': '花痴',
    'cpu': '加班', 'givemoney': '要钱', 'meow': '卖萌', 'love': '喜欢',
    'cry': '哭', 'laugh': '笑', 'eat': '干饭', 'drink': '喝',
    'hello': '打招呼', 'bye': '再见', 'think': '思考', 'cool': '酷',
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
                图们.append({
                    '相对': f'sticker-packs/{包}/memes/{标签}/{文件}',
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
