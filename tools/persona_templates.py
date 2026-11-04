#!/usr/bin/env python3
"""人设的仓库副本 ↔ 本机 profile 对账工具。

为什么要有这个：人设真正生效的那份在

    ~/.dsh/profiles/web/cordis.patch.yml

仓库里的 `deploy/preset-*.yml.template` 只是副本。副本以前靠手抄，行号一漂就找不到；
而且 chonglang 那份里有一个真实 QQ 号（老爹），不能原样进公开仓库。

所以这里做两件事：
    --check   仓库副本和本机是否一致（不一致退出码 1，可以挂进任何检查里）
    --write   用本机的现状重写仓库副本（真实号码按 MASK 自动打码）

按**内容**找块，不按行号：从 `    - id: preset-<名>` 起到下一个同级 `    - id: `
或文件尾。模板文件的结构固定是「一段注释头 + `- insert:` + 块」。

用法：
    python3 tools/persona_templates.py --check
    python3 tools/persona_templates.py --write
"""
import argparse
import difflib
import json
import os
import re
import sys

PROFILE = os.path.expanduser('~/.dsh/profiles/web/cordis.patch.yml')
根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 打码：号码本身**不写在这个文件里**（仓库是公开的）。
# 「老爹」= 桥配置里那条私聊绑定的人 —— 从 ~/.dsh/qq-bridge-config.json 现读。
# 人设里要是出现别人的号码，这里兜底打成 <号码>，并在 --check 里喊一声。
CONFIG = os.path.expanduser('~/.dsh/qq-bridge-config.json')
老爹占位 = '<老爹QQ>'

PRESETS = [
    ('xiaofeiyu', 'deploy/preset-xiaofeiyu.yml.template'),
    ('chonglang', 'deploy/preset-chonglang.yml.template'),
]


def 打码表():
    """真实号码 → 占位符。读不到配置就返回空表（那就只能靠通用兜底）。"""
    表 = {}
    try:
        j = json.load(open(CONFIG, encoding='utf-8'))
        for b in j.get('绑定') or []:
            if b.get('类型') == '私聊' and b.get('号码'):
                表[str(b['号码'])] = 老爹占位
    except Exception:
        pass
    return 表


def 取块(文本, 名):
    """从 profile 里按内容抠出 preset-<名> 那一块（含 4 空格缩进的 `- id:` 行）。"""
    行们 = 文本.splitlines()
    start = None
    for i, l in enumerate(行们):
        if l.strip() == '- id: preset-' + 名:
            start = i
            break
    if start is None:
        raise SystemExit('profile 里找不到 preset-' + 名)
    for j in range(start + 1, len(行们)):
        if re.match(r'^ {4}- id: ', 行们[j]):
            return 行们[start:j]
    return 行们[start:]


def 打码(行们, 表):
    out = []
    for l in 行们:
        for 真, 假 in 表.items():
            l = l.replace(真, 假)
        # 兜底：表里没有的号码（6 位以上，QQ 号最短 5 位这里从严）一律打成通用占位符，绝不原样进仓库
        l = re.sub(r'(?<!\d)\d{6,12}(?!\d)', '<号码>', l)
        out.append(l)
    return out


def 拆模板(路径):
    """返回 (块, 头)。头是到 `- insert:` 那一行为止（含）。"""
    行们 = open(路径, encoding='utf-8').read().splitlines()
    for i, l in enumerate(行们):
        if l == '- insert:':
            return 行们[i + 1:], 行们[:i + 1]
    raise SystemExit(路径 + ' 里没有 `- insert:`')


def 收尾(行们):
    """去掉尾部空行，方便比较。"""
    while 行们 and not 行们[-1].strip():
        行们 = 行们[:-1]
    return 行们


def main():
    ap = argparse.ArgumentParser(description='人设模板对账')
    ap.add_argument('--check', action='store_true', help='仓库副本和本机是否一致')
    ap.add_argument('--write', action='store_true', help='用本机现状重写仓库副本')
    a = ap.parse_args()
    if not (a.check or a.write):
        ap.print_help()
        return 2

    本机 = open(PROFILE, encoding='utf-8').read()
    表 = 打码表()
    坏 = 0
    for 名, 相对 in PRESETS:
        块 = 打码(取块(本机, 名), 表)
        路径 = os.path.join(根, 相对)

        if a.write:
            头 = []
            if os.path.exists(路径):
                _, 头 = 拆模板(路径)
            内容 = '\n'.join(头 + 块) + '\n'
            open(路径, 'w', encoding='utf-8').write(内容)
            print('写好 %s（%d 行）' % (相对, len(块)))
            continue

        if not os.path.exists(路径):
            print('✗ %s：缺文件 %s' % (名, 相对))
            坏 += 1
            continue
        体, _ = 拆模板(路径)
        if 收尾(体) == 收尾(块):
            print('✓ %s：仓库副本和本机一致（%d 行）' % (名, len(块)))
        else:
            坏 += 1
            print('✗ %s：不一致（%s）' % (名, 相对))
            for l in list(difflib.unified_diff(体, 块, '仓库', '本机', lineterm='', n=1))[:24]:
                print('   ' + l)

    # 兜底：打完码还留着 6 位以上的数字，多半是有新号码忘了加进 MASK
    for 名, 相对 in PRESETS:
        路径 = os.path.join(根, 相对)
        if not os.path.exists(路径):
            continue
        体, _ = 拆模板(路径)
        for l in 体:
            for m in re.findall(r'\d{6,}', l):
                print('⚠ %s 里有没打码的长数字：%s —— 是号码就加进打码表' % (相对, m))
                坏 += 1

    return 1 if 坏 else 0


if __name__ == '__main__':
    sys.exit(main())
