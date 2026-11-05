#!/usr/bin/env python3
"""用 MemeCrafters/meme-generator 现做一张表情。

跟 nonebot-plugin-memes 是同一个引擎（本机装的是 0.2.x 的 Rust 绑定）。
桥不把路径交给模型：这里只接受「关键词 + 若干句配文 + 一张已经下好的头像」，
图只写进调用方指定的输出目录。

    python qq_meme.py search 摸
    python qq_meme.py make --query 摸 --text 一句 --image 头像.png \\
        --image-root <入目录> --out-dir <出目录>

stdout 只有一行 JSON。缺资源时会自己补一次（要能上网）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

_关键词 = re.compile(r'^[\w-]{1,40}$', re.UNICODE)


def 洗关键词(值):
    文 = str(值 or '').strip()
    if not _关键词.fullmatch(文):
        return ''
    return 文


def 路径在目录内(路径, 目录):
    """realpath 之后必须落在目录里面。过不了就返回空串，调用方不许用这个路径。"""
    if not 路径 or not 目录:
        return ''
    try:
        实 = os.path.realpath(路径)
        根 = os.path.realpath(目录)
    except OSError:
        return ''
    if os.path.isdir(实):
        return ''
    if 实 == 根 or 实.startswith(根 + os.sep):
        return 实
    return ''


def 目录本身(路径):
    if not 路径:
        return ''
    try:
        实 = os.path.realpath(路径)
    except OSError:
        return ''
    if os.path.isdir(实):
        return 实
    return ''


def _说完(对象, 码=0):
    sys.stdout.write(json.dumps(对象, ensure_ascii=False) + '\n')
    raise SystemExit(码)


def _静音():
    """字体库会往 stderr 刷一屏 fontconfig 警告，桥只看 stdout 的 JSON。"""
    try:
        空 = os.open(os.devnull, os.O_WRONLY)
        os.dup2(空, 2)
        os.close(空)
    except OSError:
        pass


def _引擎():
    _静音()
    import meme_generator
    from meme_generator.resources import check_resources
    return meme_generator, check_resources


def _一条(meme):
    信息 = meme.info
    参 = 信息.params
    词 = list(信息.keywords)
    return {
        'key': meme.key,
        'keywords': 词[:4],
        'images': [int(参.min_images), int(参.max_images)],
        'texts': [int(参.min_texts), int(参.max_texts)],
    }


def _找(mg, 词):
    精确 = mg.get_meme(词)
    if 精确 is not None:
        return 精确, []
    命中 = []
    for 键 in list(mg.search_memes(词))[:8]:
        条 = mg.get_meme(键)
        if 条 is not None:
            命中.append(条)
    if len(命中) == 1:
        return 命中[0], []
    return None, 命中


def _接近(命中):
    段 = []
    for 条 in 命中[:6]:
        词 = list(条.info.keywords)
        段.append((词[0] if 词 else 条.key) + '(' + 条.key + ')')
    return '、'.join(段)


def 命令搜索(词):
    词 = 洗关键词(词)
    if not 词:
        _说完({'ok': False, '说': '关键词不行（只收中文、英文、数字、下划线）。'})
    mg, _检查 = _引擎()
    条, 命中 = _找(mg, 词)
    if 条 is not None:
        简介 = _一条(条)
        _说完({'ok': True, '说': '有这张：' + (简介['keywords'][0] if 简介['keywords'] else 条.key), 'meme': 简介})
    if not 命中:
        _说完({'ok': False, '说': '没有叫「' + 词 + '」的。换个说法再试，比如 摸、拍、亲、悲报。'})
    _说完({'ok': False, '说': '「' + 词 + '」对上好几张：' + _接近(命中) + '。挑一个再调。'})


def _后缀(数据):
    if 数据[:3] == b'GIF':
        return '.gif'
    if 数据[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png'
    if 数据[:4] == b'RIFF' and 数据[8:12] == b'WEBP':
        return '.webp'
    if 数据[:2] == b'\xff\xd8':
        return '.jpg'
    return ''


def 落盘计划(数据):
    """GIF 不落成 .gif。

    看图接口（Grok）只收 JPG/PNG/WebP/ICO。谁要是把 .gif 读进去，整轮 400，
    而且这张图会留在对话历史里，后面连压缩都过不去。
    动图字节写到 .gifdata（QQ 按内容认，不看后缀），另外尽量抽一帧 PNG 给人看。
    """
    后缀 = _后缀(数据 if isinstance(数据, (bytes, bytearray)) else b'')
    if 后缀 == '.gif':
        return '.gifdata', '.png'
    return 后缀, ''


def _首帧png(数据):
    """GIF 的第一帧。没有 ffmpeg 或抽失败就返回空字节，调用方只发动图。"""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return b''
    try:
        with tempfile.TemporaryDirectory(prefix='qq-meme-') as 临时:
            入 = os.path.join(临时, 'in.gif')
            出 = os.path.join(临时, 'out.png')
            with open(入, 'wb') as f:
                f.write(数据)
            跑 = subprocess.run(
                [ffmpeg, '-y', '-v', 'error', '-i', 入, '-frames:v', '1', 出],
                timeout=15,
                capture_output=True,
            )
            if 跑.returncode != 0 or not os.path.isfile(出):
                return b''
            with open(出, 'rb') as f:
                预览 = f.read()
    except (OSError, subprocess.SubprocessError):
        return b''
    if _后缀(预览) != '.png' or len(预览) < 32:
        return b''
    return 预览


def 命令制作(参数):
    词 = 洗关键词(参数.query)
    if not 词:
        _说完({'ok': False, '说': '关键词不行（只收中文、英文、数字、下划线）。'})
    出目录 = 目录本身(参数.out_dir)
    if not 出目录:
        _说完({'ok': False, '说': '输出目录不存在，这张没做。'})
    图路径 = ''
    if 参数.image:
        根 = 目录本身(参数.image_root)
        图路径 = 路径在目录内(参数.image, 根) if 根 else ''
        if not 图路径:
            _说完({'ok': False, '说': '头像路径不在允许的目录里，这张没做。'})
    配文 = []
    for 句 in (参数.text or []):
        句 = str(句 or '').strip()
        if not 句:
            continue
        if len(句) > 60:
            _说完({'ok': False, '说': '配文太长（一句最多 60 字），这张没做。'})
        配文.append(句)
        if len(配文) >= 4:
            break

    mg, 检查资源 = _引擎()
    try:
        检查资源()
    except Exception as 错:
        _说完({'ok': False, '说': '表情资源没补上（' + str(错).splitlines()[-1][:80] + '），这张没做。'})

    条, 命中 = _找(mg, 词)
    if 条 is None:
        if not 命中:
            _说完({'ok': False, '说': '没有叫「' + 词 + '」的。换个说法，比如 摸、拍、亲、悲报、鲁迅说。'})
        _说完({'ok': False, '说': '「' + 词 + '」对上好几张：' + _接近(命中) + '。挑一个再调，别猜。'})

    参 = 条.info.params
    要图 = int(参.min_images)
    最多图 = int(参.max_images)
    要字 = int(参.min_texts)
    最多字 = int(参.max_texts)
    名 = (list(条.info.keywords) or [条.key])[0]
    if 要图 > 1:
        _说完({'ok': False, '说': '「' + 名 + '」要 ' + str(要图) + ' 张图，我这边一次只有一张头像，做不了。换一张只要一张或者不要图的。'})
    if 要图 >= 1 and not 图路径:
        _说完({'ok': False, '说': '「' + 名 + '」要用一张头像，这次没拿到，先用文字回吧。'})
    if 要字 > len(配文):
        _说完({'ok': False, '说': '「' + 名 + '」要配 ' + str(要字) + ' 句话，写在 text 里再用 | 隔开。'})
    if len(配文) > 最多字:
        配文 = 配文[:最多字]
    图们 = []
    if 图路径 and 最多图 >= 1:
        try:
            数据 = open(图路径, 'rb').read()
        except OSError:
            _说完({'ok': False, '说': '头像读不出来，这张没做。'})
        if len(数据) < 32 or len(数据) > 2_000_000:
            _说完({'ok': False, '说': '头像大小不对，这张没做。'})
        图们 = [mg.Image(name=os.path.basename(图路径), data=数据)]

    try:
        成品 = 条.generate(图们, 配文, {})
    except Exception as 错:
        类 = type(错).__name__
        if 类 == 'TextOverLength':
            _说完({'ok': False, '说': '「' + 名 + '」装不下这么长的字，缩短再试。'})
        if 类 in ('TextNumberMismatch', 'ImageNumberMismatch'):
            _说完({'ok': False, '说': '「' + 名 + '」的图或字数量不对（图 ' + str(要图) + '–' + str(最多图) + '，字 ' + str(要字) + '–' + str(最多字) + '）。'})
        _说完({'ok': False, '说': '「' + 名 + '」没做出来（' + 类 + '）。换一张吧。'})
    if not isinstance(成品, (bytes, bytearray)) or len(成品) < 32:
        _说完({'ok': False, '说': '「' + 名 + '」做出来是空的。'})
    成品字节 = bytes(成品)
    后缀 = _后缀(成品字节)
    if not 后缀:
        _说完({'ok': False, '说': '「' + 名 + '」做出来的不是图片。'})
    发送后缀, 预览后缀 = 落盘计划(成品字节)
    基 = os.path.join(出目录, 'meme-' + str(int(time.time() * 1000)) + '-' + 条.key)
    动图 = 基 + 发送后缀 if 发送后缀 == '.gifdata' else ''
    文件 = 基 + (预览后缀 or 发送后缀)
    # 再核一次：文件名是我们起的，realpath 仍得在出目录里
    for 候选 in (文件, 动图):
        if 候选 and not 路径在目录内(候选, 出目录) and os.path.dirname(os.path.realpath(候选)) != 出目录:
            _说完({'ok': False, '说': '输出路径不在允许的目录里，这张没写盘。'})
    预览 = _首帧png(成品字节) if 动图 else b''
    if 动图:
        with open(动图, 'wb') as f:
            f.write(成品字节)
    if 预览:
        with open(文件, 'wb') as f:
            f.write(预览)
    elif not 动图:
        with open(文件, 'wb') as f:
            f.write(成品字节)
    else:
        # 抽不出静帧：没有 PNG 可看，发送仍用动图字节
        文件 = 动图
    结果 = {'ok': True, 'file': 文件, 'key': 条.key, '说': '做好了（' + 名 + '）。'}
    if 动图 and 动图 != 文件:
        结果['anim'] = 动图
    _说完(结果)


def main(argv):
    解 = argparse.ArgumentParser(add_help=True)
    子 = 解.add_subparsers(dest='cmd', required=True)
    搜 = 子.add_parser('search')
    搜.add_argument('query')
    做 = 子.add_parser('make')
    做.add_argument('--query', required=True)
    做.add_argument('--text', action='append', default=[])
    做.add_argument('--image', default='')
    做.add_argument('--image-root', default='')
    做.add_argument('--out-dir', required=True)
    参数 = 解.parse_args(argv)
    if 参数.cmd == 'search':
        命令搜索(参数.query)
    else:
        命令制作(参数)


if __name__ == '__main__':
    main(sys.argv[1:])
