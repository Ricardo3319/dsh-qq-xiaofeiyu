#!/usr/bin/env python3
"""去网上把这支歌的**能唱的简谱**找回来。

为什么要单独写个 Python：歌谱站（jianpu.cn 等）的页面常常是 **GBK**，Node 没有内置
GBK 解码/编码器，Python 一行就够。

为什么不让模型自己搜：机器人在 DSH 里的联网工具搜不到东西（DDG 在这台机器上返回
反爬挑战页）。这里自己搜。

为什么要筛「五线谱」：2026-11-01 用户点《无敌》，搜回来的第一张是 jianpu.cn 的
**钢琴五线谱**（还没有歌词），模型看了看不懂，只能回头跟人要简谱 —— 用户当场炸了。
所以这里直接按像素筛：**五线谱有横贯整页的谱线，简谱没有**。见 是五线谱()。

为什么要多引擎：搜狗搜十几次就跳 /antispider/ 验证码页，旧代码把它当成「没搜到」，
于是机器人会说「网上没有」，其实是**被拦了**。现在搜狗被拦就换 360、再换必应。

用法：
    python qq_score.py --song 孤勇者 --out ~/.dsh/qq-sing/scores
    python qq_score.py --song 孤勇者 --list          # 只搜，不取谱
    python qq_score.py --song 孤勇者 --skip http://x  # 跳过某个页面（换一张谱）
输出：stdout 一行 JSON：
    {"ok": true, "查询": ..., "引擎": [...], "候选": [{标题,页面}...],
     "页面": ..., "标题": ..., "图片": ["/abs/x.jpg"], "文字谱": "",
     "谱种": "简谱"|"五线谱"|"", "说明": ""}
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')

# 谱子站权重：苍强曲谱那种「带歌词的简谱」最有用，权重给最高。
谱站 = {
    'cangqiang.com.cn': 130,
    'milianshe': 40,
    'jianpu.cn': 55,
    'jianpu.net': 45,
    'qupu123.com': 45,
    'zhaogepu': 45,
    'gepu123': 35,
    'chnmusic': 25,
    'yuepuku': 25,
    'gangqinpu.com': 15,       # 「钢琴简谱 数字双手」：是数字谱，但没歌词，别排前面
    'tan8.com': 15,
    '17jita': 5,
    '91pu': 5,
}

# 标题里出现这些，基本不是能唱的简谱（伴奏谱 / 视频 / 文档）
标题减分词 = ('五线谱', '钢琴谱', '吉他谱', '弹唱', 'gtp', '伴奏', '原版', '视频', 'mv',
              '文库', '文档', 'pdf', 'docx', '原神', '光遇', '琴谱一览', '教学', '教程')
地址减分词 = ('bilibili', 'y.qq.com', 'music.163', 'weixin', 'zhihu', 'iqiyi', 'toutiao',
              'book118', 'wenku', '3dmgame', '17173', 'jitashe',
              # jp114「简谱库」是 SEO 垃圾站：页面里塞的是图库照片，不是谱子
              'jp114', 'baike.baidu')


def 取页面(地址, 超时=15, 引用=None):
    # ⚠ Referer 别乱给：搜狗那个 Referer 会把图床惹毛（cangqiang 的谱子图直接 403）。
    #   默认按浏览器那样，用目标站自己的域名当来源。
    if 引用 is None:
        p = urllib.parse.urlparse(地址)
        引用 = '%s://%s/' % (p.scheme, p.netloc) if p.scheme and p.netloc else ''
    req = urllib.request.Request(地址, headers={
        'User-Agent': UA,
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 引用,
    })
    # 国内站走代理反而更慢/被拦，绕开代理直连
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=超时) as r:
        return r.read(), r.geturl()


def 解码(字节):
    for 编码 in ('utf-8', 'gbk'):
        try:
            return 字节.decode(编码)
        except Exception:
            continue
    return 字节.decode('utf-8', 'ignore')


def 解析跳转(页):
    """搜索结果是 /link?url=… 包一层，真地址写在 JS 跳转里。"""
    m = re.search(r'location\.replace\(["\']([^"\']+)["\']\)', 页)
    if m:
        return m.group(1)
    m = re.search(r'URL=\'?([^\'"<>]+)', 页)
    return m.group(1) if m else ''


# ── 搜索：三个引擎轮着来 ────────────────────────────────────────────────
# 搜狗被拦过就记一笔，15 分钟内直接跳过它 —— 免得每次点歌都先白跑一趟验证码页。
封锁标记 = Path.home() / '.dsh' / 'qq-sing' / 'sogou-blocked'
封锁多久 = 900


def _刚被拦():
    try:
        return time.time() - 封锁标记.stat().st_mtime < 封锁多久
    except Exception:  # noqa: BLE001
        return False


def _记被拦():
    try:
        封锁标记.parent.mkdir(parents=True, exist_ok=True)
        封锁标记.write_text(str(int(time.time())), encoding='utf-8')
    except Exception:  # noqa: BLE001
        pass


def 搜搜狗(名字, 条数):
    if _刚被拦():
        return [], '被拦(刚拦过)'
    q = urllib.parse.quote('%s 简谱' % 名字)
    字节, 终址 = 取页面('https://www.sogou.com/web?query=' + q)
    if '/antispider/' in 终址:
        _记被拦()
        return [], '被拦'
    页 = 解码(字节)
    if 'antispider' in 页[:4000] or '请输入验证码' in 页[-4000:]:
        _记被拦()
        return [], '被拦'
    出 = []
    见过 = set()
    for 块 in re.split(r'<div class="(?:vrwrap|rb)"', 页)[1:]:
        m = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', 块, re.S)
        if not m:
            continue
        标题 = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        链接 = urllib.parse.urljoin('https://www.sogou.com/', m.group(1))
        if not 链接.startswith('http'):
            continue
        if '/link?' in 链接:
            try:
                子, _ = 取页面(链接, 12)
                真 = 解析跳转(解码(子))
            except Exception:  # noqa: BLE001
                真 = ''
            if not 真:
                continue
            链接 = 真
        if 链接 in 见过:
            continue
        见过.add(链接)
        出.append({'标题': 标题, '页面': 链接})
        if len(出) >= 条数:
            break
    return 出, '好' if 出 else '空'


def 搜360(名字, 条数):
    q = urllib.parse.quote('%s 简谱' % 名字)
    字节, 终址 = 取页面('https://www.so.com/s?q=' + q)
    页 = 解码(字节)
    if '/antispider' in 终址 or '请输入验证码' in 页:
        return [], '被拦'
    出 = []
    见过 = set()
    for 块 in re.findall(r'<h3[^>]*>(.*?)</h3>', 页, re.S):
        m = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', 块, re.S)
        if not m:
            continue
        标题 = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        链接 = urllib.parse.urljoin('https://www.so.com/', m.group(1))
        if not 链接.startswith('http'):
            continue
        # 360 的结果本身也是 /link? 包一层，别把这个当「站内页」丢掉
        if 'so.com' in 链接 and '/link?' not in 链接:
            continue          # 站内页（图片搜索/文库）不要
        if '/link?' in 链接:
            try:
                子, 真址 = 取页面(链接, 12)
                if 真址 and '/link?' not in 真址:
                    链接 = 真址
                else:
                    真 = 解析跳转(解码(子))
                    if not 真:
                        continue
                    链接 = 真
            except Exception:  # noqa: BLE001
                continue
        if 链接 in 见过:
            continue
        见过.add(链接)
        if not 标题:
            标题 = 链接
        出.append({'标题': 标题, '页面': 链接})
        if len(出) >= 条数:
            break
    return 出, '好' if 出 else '空'


def 搜必应(名字, 条数):
    q = urllib.parse.quote('%s 简谱' % 名字)
    字节, 终址 = 取页面('https://cn.bing.com/search?q=' + q)
    页 = 解码(字节)
    出 = []
    见过 = set()
    for 块 in re.findall(r'<li class="b_algo".*?</li>', 页, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', 块, re.S)
        if not m:
            continue
        标题 = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        链接 = m.group(1)
        if not 链接.startswith('http') or 链接 in 见过:
            continue
        见过.add(链接)
        出.append({'标题': 标题, '页面': 链接})
        if len(出) >= 条数:
            break
    return 出, '好' if 出 else '空'


def 搜索(名字, 条数=10):
    """搜狗 → 360 → 必应。返回 (候选, 引擎状态列表)。

    搜狗搜十几次会跳 /antispider/ 验证页 —— 那不是「没这首歌」，是**被拦了**，
    所以要换引擎，并且把状态带回去让上层如实说。
    """
    记 = []
    for 引擎, 函数 in (('搜狗', 搜搜狗), ('360', 搜360), ('必应', 搜必应)):
        try:
            结果, 态 = 函数(名字, 条数)
        except Exception as e:  # noqa: BLE001
            结果, 态 = [], '失败:' + str(e)[:40]
        记.append('%s=%s(%d)' % (引擎, 态, len(结果)))
        if 结果:
            return 结果, 记
        time.sleep(1.0)
    return [], 记


def 排序(候选, 名字):
    净名 = re.sub(r'[^一-鿿A-Za-z0-9]', '', 名字)

    def 分(x):
        s = 0
        u = x['页面'].lower()
        t = x['标题']
        for 域, 权 in 谱站.items():
            if 域 in u:
                s += 权
                break
        for k in 标题减分词:
            if k in t.lower():
                s -= 45
        for k in 地址减分词:
            if k in u:
                s -= 80
        if '简谱' in t and not any(k in t for k in ('五线', '钢琴', '吉他')):
            s += 35
        if 净名 and 净名 in re.sub(r'[^一-鿿A-Za-z0-9]', '', t):
            s += 20
        return -s

    return sorted(候选, key=分)


def 取谱(地址):
    """页面 → (图片直链列表, 文字谱)。谱子基本是图片；少数页面正文里就有数字谱。"""
    字节, _ = 取页面(地址, 25)
    页 = 解码(字节)
    图 = []
    m = re.search(r"<div id=['\"]jianpu['\"]>(.*?)</div>", 页, re.S)
    片段 = m.group(1) if m else 页
    for u in re.findall(r'<img[^>]+src=[\'"]([^\'"]+)[\'"]', 片段):
        if any(k in u for k in ('logo', 'icon', 'button', 'banner', 'ad_', '/js/', 'static')):
            continue
        if u.startswith('//'):
            u = 'http:' + u
        elif u.startswith('/'):
            u = urllib.parse.urljoin(地址, u)
        图.append(u)
    文字 = ''
    正文 = re.sub(r'<script[\s\S]*?</script>', ' ', 页)
    正文 = re.sub(r'<[^>]+>', ' ', 正文)
    for 行 in 正文.split('\n'):
        行 = 行.strip()
        if len(行) < 12:
            continue
        数字 = len(re.findall(r'[1-7]', 行))
        if 数字 >= 10 and 数字 * 2 >= len(行):
            文字 = 行
            break
    return 图, 文字


def 图片尺寸(字节):
    """从字节里量出 (宽, 高)。认不出返回 (0, 0)。

    为什么要量：谱子站旁边全是 logo / 图标 / 按钮，抠 src 会把它们一起抠出来
    （虫虫钢琴那次就抠回一张 YJ Music 的 logo）。谱子图一眼就能认出来 —— 又高又大。
    """
    try:
        if 字节[:2] == b'\xff\xd8':                      # JPEG
            i = 2
            while i < len(字节) - 9:
                if 字节[i] != 0xFF:
                    i += 1
                    continue
                标 = 字节[i + 1]
                if 标 in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                    h = 字节[i + 5] * 256 + 字节[i + 6]
                    w = 字节[i + 7] * 256 + 字节[i + 8]
                    return w, h
                长 = 字节[i + 2] * 256 + 字节[i + 3]
                i += 2 + (长 or 0)
        if 字节[:8] == b'\x89PNG\r\n\x1a\n':             # PNG
            return (字节[16] * 16777216 + 字节[17] * 65536 + 字节[18] * 256 + 字节[19],
                    字节[20] * 16777216 + 字节[21] * 65536 + 字节[22] * 256 + 字节[23])
        if 字节[:3] == b'GIF':                            # GIF
            return (字节[6] + 字节[7] * 256, 字节[8] + 字节[9] * 256)
    except Exception:  # noqa: BLE001
        pass
    return 0, 0


def 是五线谱(字节):
    """这张图是不是**五线谱**。认不出返回 None（那就当它可用）。

    道理：五线谱的谱线是横贯整页的长横线；简谱只有数字底下很短的减时线。
    2026-11-01 实测：孤勇者简谱（900 宽）达到半页宽的长横线 0~2 行，
    无敌钢琴五线谱 94 行。差得很开，阈值取 20 很安全。
    """
    try:
        import io

        import numpy as np
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    try:
        im = Image.open(io.BytesIO(字节)).convert('L')
        宽0, 高0 = im.size
        if 宽0 < 200 or 高0 < 200:
            return None
        宽 = 900
        im = im.resize((宽, max(1, int(高0 * 宽 / 宽0))), Image.LANCZOS)
        阵 = np.asarray(im) < 128
        过半 = 0
        for 行 in 阵:
            if not 行.any():
                continue
            d = np.diff(np.concatenate(([0], 行.view(np.int8), [0])))
            起 = np.where(d == 1)[0]
            if not len(起):
                continue
            止 = np.where(d == -1)[0]
            if (止 - 起).max() >= 0.5 * 宽:
                过半 += 1
        return 过半 >= 20
    except Exception:  # noqa: BLE001
        return None


def 像谱子(字节):
    """这张图**看着像不像谱子**。认不出返回 None。

    为什么还要这一道：只剩尺寸门槛时，jp114 那种 SEO 垃圾站会把一张
    500x500 的**弹吉他人物照**塞进来（2026-11-01 实测，真踩到了）。
    谱子的特征很好认：白底黑字、几乎没有彩色。实拍图彩色占比高、白底少。
    实测：真谱 白≥0.82 彩=0.00；人物照 白≤0.50 彩≥0.20。
    """
    try:
        import io

        import numpy as np
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    try:
        im = Image.open(io.BytesIO(字节)).convert('RGB')
        宽0, 高0 = im.size
        if 宽0 < 200 or 高0 < 200:
            return None
        宽 = 600
        im = im.resize((宽, max(1, int(高0 * 宽 / 宽0))), Image.LANCZOS)
        阵 = np.asarray(im).astype(int)
        最大 = 阵.max(axis=2)
        最小 = 阵.min(axis=2)
        白 = float(((最小 > 190) & ((最大 - 最小) < 45)).mean())
        彩 = float(((最大 - 最小) > 45).mean())
        return 彩 <= 0.05 and 白 >= 0.60
    except Exception:  # noqa: BLE001
        return None


def 剥缩略(链接):
    """去掉图床的缩略参数（谱子站常给 300px 高的预览图）。"""
    return re.sub(r'\?(?:x-oss-process|imageView2|imageMogr2)[^"\']*$', '', 链接)


def 挑图(图们):
    """谱子图优先：fileupload / images/normal 这种路径在前。"""
    def 分(u):
        s = 0
        if 'fileupload' in u or 'images/normal' in u or '/img/' in u:
            s += 10
        if any(k in u.lower() for k in ('logo', 'icon', 'banner', 'avatar', 'head')):
            s -= 20
        return -s

    return sorted(dict.fromkeys(剥缩略(u) for u in 图们), key=分)


def 下载(链接, 到, 最小宽=480, 最小高=480):
    """下载 → 验尺寸 → 挡掉五线谱。返回 (是否可用, 原因)。"""
    try:
        字节, _ = 取页面(链接, 25)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write('图下载失败（%s）：%s\n' % (str(e)[:60], 链接))
        return False, '下载失败'
    if len(字节) < 500:
        return False, '太小'
    宽, 高 = 图片尺寸(字节)
    if 宽 and 高 and (宽 < 最小宽 or 高 < 最小高):
        sys.stderr.write('图太小当 logo 丢了（%dx%d）：%s\n' % (宽, 高, 链接))
        return False, '小图'
    if 像谱子(字节) is False:
        sys.stderr.write('不像谱子（像照片/广告），丢：%s\n' % 链接)
        return False, '不是谱子'
    五线 = 是五线谱(字节)
    if 五线 is True:
        sys.stderr.write('是五线谱，丢（唱不了）：%s\n' % 链接)
        return False, '五线谱'
    try:
        Path(到).write_bytes(字节)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write('图存不下（%s）：%s\n' % (str(e)[:60], 到))
        return False, '存盘失败'
    return True, ''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--song', required=True, help='歌名')
    ap.add_argument('--out', default='', help='谱子图片存哪，默认 ~/.dsh/qq-sing/scores')
    ap.add_argument('--max', type=int, default=8, help='最多看几个搜索结果（默认 8）')
    ap.add_argument('--try', dest='试几个', type=int, default=5, help='最多打开几个页面找谱（默认 5）')
    ap.add_argument('--skip', action='append', default=[], help='跳过这些页面（可以给多次）')
    ap.add_argument('--list', action='store_true', help='只搜不取谱')
    a = ap.parse_args()

    名字 = a.song.strip()
    if not 名字:
        raise SystemExit('没给歌名')
    输出 = Path(a.out) if a.out else (Path.home() / '.dsh' / 'qq-sing' / 'scores')
    跳过 = {str(x) for x in (a.skip or [])}

    候选, 引擎 = 搜索(名字, a.max)
    候选 = [x for x in 排序(候选, 名字) if x['页面'] not in 跳过]
    结果 = {'ok': False, '查询': 名字, '引擎': 引擎, '候选': 候选}
    if not 候选:
        结果['错'] = '没搜到「%s」的谱子' % 名字
        if all('被拦' in x for x in 引擎):
            结果['错'] = '搜索站把我拦了（验证码），过一会儿再试'
        结果['被拦'] = all('被拦' in x for x in 引擎)
        print(json.dumps(结果, ensure_ascii=False))
        return 0
    if a.list:
        结果['ok'] = True
        print(json.dumps(结果, ensure_ascii=False))
        return 0

    输出.mkdir(parents=True, exist_ok=True)
    见过五线谱 = []
    for i, x in enumerate(候选[:max(1, a.试几个)], 1):
        try:
            图, 文字 = 取谱(x['页面'])
        except Exception as e:  # noqa: BLE001
            sys.stderr.write('第 %d 个打不开（%s）：%s\n' % (i, x['页面'], str(e)[:60]))
            continue
        图本地 = []
        for j, u in enumerate(挑图(图)[:6], 1):
            后缀 = Path(urllib.parse.urlparse(u).path).suffix.lower()
            if 后缀 not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                后缀 = '.jpg'
            到 = 输出 / ('%s-%d-%d%s' % (re.sub(r'[^一-鿿A-Za-z0-9]', '', 名字)[:12], i, j, 后缀))
            可用, 原因 = 下载(u, 到)
            if 可用:
                图本地.append(str(到))
                if len(图本地) >= 2:      # 一首歌一般一张（多页的取前两张）
                    break
            elif 原因 == '五线谱':
                见过五线谱.append(x['标题'])
        if not 图本地 and not 文字:
            continue
        结果.update({'ok': True, '页面': x['页面'], '标题': x['标题'],
                     '图片': 图本地, '文字谱': 文字, '谱种': '简谱' if 图本地 else '',
                     '说明': '已挡掉五线谱：' + '、'.join(dict.fromkeys(见过五线谱)) if 图本地 and 见过五线谱 else ''})
        break
    if not 结果['ok']:
        结果['错'] = ('搜到了页面，但只找到五线谱/小图' if 见过五线谱
                     else '搜到条目了，但没取到谱子图')
        结果['见过五线谱'] = list(dict.fromkeys(见过五线谱))
        结果.update({'图片': [], '文字谱': ''})
    print(json.dumps(结果, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
