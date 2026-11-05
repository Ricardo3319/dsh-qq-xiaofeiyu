#!/usr/bin/env python3
"""qq_meme 的路径白名单和关键词清洗。不 import 引擎，没装 meme-generator 也能跑。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qq_meme as m


def 期望(条件, 话):
    if not 条件:
        raise SystemExit('失败：' + 话)


def main():
    期望(m.洗关键词('摸') == '摸', '中文关键词')
    期望(m.洗关键词('petpet') == 'petpet', '英文 key')
    期望(m.洗关键词('鲁迅说') == '鲁迅说', '多字中文')
    期望(m.洗关键词('../etc/passwd') == '', '拒绝路径')
    期望(m.洗关键词('a b') == '', '拒绝空格')
    期望(m.洗关键词('a;rm') == '', '拒绝分号')
    期望(m.洗关键词('') == '', '拒绝空')
    期望(m.洗关键词('x' * 41) == '', '拒绝过长')
    期望(m.落盘计划(b'GIF89a' + b'\x00' * 20) == ('.gifdata', '.png'), 'GIF 不落成 .gif')
    期望(m.落盘计划(b'\x89PNG\r\n\x1a\n' + b'\x00' * 20) == ('.png', ''), 'PNG 照旧')
    期望(m.落盘计划(b'\xff\xd8' + b'\x00' * 20) == ('.jpg', ''), 'JPG 照旧')
    期望(m.落盘计划(b'not-an-image') == ('', ''), '不是图就不落盘')

    with tempfile.TemporaryDirectory() as 家:
        内 = os.path.join(家, 'in')
        os.mkdir(内)
        图 = os.path.join(内, 'a.png')
        with open(图, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'0' * 40)
        期望(m.路径在目录内(图, 内) == os.path.realpath(图), '目录内的图可以')
        期望(m.路径在目录内('/etc/passwd', 内) == '', '目录外的文件不行')
        外 = os.path.join(家, 'out-link')
        os.symlink('/etc/passwd', 外)
        期望(m.路径在目录内(外, 内) == '', '指到目录外的软链不行')
        期望(m.路径在目录内(内, 内) == '', '目录本身不是一张图')
    print('qq_meme 白名单：过')


if __name__ == '__main__':
    main()
