#!/usr/bin/env python3
"""零样本克隆 TTS（F5-TTS）：用参考音频的音色说话。

给桥的「语音合成命令」用（约定跟 qq_tts.py 一样）：
    <qq-clone 的 python> qq_clone_tts.py --out {out}
文字从 stdin 读，音频写到 --out（mp3）。

参考音频 / 文本默认是 ~/.dsh/qq-clone/ref.wav / ref.txt；
可以用 --ref / --ref-text 覆盖，或者用环境变量 QQ_CLONE_REF / QQ_CLONE_REF_TEXT。

为什么单独一个脚本：F5-TTS 的环境和语音识别 / DiffSinger 不是同一个
（它要 torchaudio + vocos + CUDA torch），桥只认「一条命令 + {out}」。
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def 默认参考():
    d = Path.home() / '.dsh' / 'qq-clone'
    return d / 'ref.wav', d / 'ref.txt'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--ref', default=os.environ.get('QQ_CLONE_REF', ''))
    ap.add_argument('--ref-text', default=os.environ.get('QQ_CLONE_REF_TEXT', ''))
    ap.add_argument('--device', default=os.environ.get('QQ_CLONE_DEVICE', ''))
    ap.add_argument('--speed', type=float, default=1.0)
    ap.add_argument('--max-chars', type=int, default=300)
    a = ap.parse_args()

    默认音频, 默认文本 = 默认参考()
    ref = Path(a.ref) if a.ref else 默认音频
    ref_text = a.ref_text
    if not ref_text:
        try:
            ref_text = 默认文本.read_text(encoding='utf-8').strip()
        except Exception:
            ref_text = ''
    if not ref.exists():
        sys.stderr.write('参考音频不存在：%s\n' % ref)
        return 2
    if not ref_text:
        sys.stderr.write('没有参考文本（--ref-text 或 %s）\n' % 默认文本)
        return 2

    text = ' '.join(sys.stdin.read().split()).strip()
    if not text:
        sys.stderr.write('没有从 stdin 读到文字\n')
        return 2
    if len(text) > a.max_chars:
        text = text[: a.max_chars]
        sys.stderr.write('文本过长，已截到 %d 字\n' % a.max_chars)

    # 这台机器的 all_proxy 是 socks5://，而 huggingface_hub 用的 httpx 没装 socksio，
    # 一上来就报 "Using SOCKS proxy, but the 'socksio' package is not installed"。
    # HTTP(S)_PROXY 是能用的，所以只摘掉 SOCKS 那一条。
    os.environ.pop('ALL_PROXY', None)
    os.environ.pop('all_proxy', None)

    try:
        from f5_tts.api import F5TTS
        import soundfile as sf
    except Exception as e:  # noqa: BLE001
        sys.stderr.write('F5-TTS 环境没装好：%s\n' % e)
        return 3

    device = a.device.strip()
    if not device:
        try:
            import torch
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        except Exception:
            device = 'cpu'

    try:
        f5 = F5TTS(model='F5TTS_v1_Base', device=device)
    except TypeError:
        # 老一点的 f5-tts 没有 device 参数
        try:
            f5 = F5TTS(model='F5TTS_v1_Base')
        except Exception as e:  # noqa: BLE001
            sys.stderr.write('F5-TTS 加载失败：%s\n' % e)
            return 4
    except Exception as e:  # noqa: BLE001
        sys.stderr.write('F5-TTS 加载失败：%s\n' % e)
        return 4

    fd, tmp_name = tempfile.mkstemp(prefix='qq-clone-', suffix='.wav')
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        参数 = dict(ref_file=str(ref), ref_text=ref_text, gen_text=text,
                  file_wave=str(tmp), speed=float(a.speed))
        try:
            f5.infer(**参数)
        except TypeError:
            参数.pop('speed', None)
            f5.infer(**参数)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write('F5-TTS 推理失败：%s\n' % e)
            return 4
        if not tmp.exists() or tmp.stat().st_size == 0:
            sys.stderr.write('F5-TTS 没产出音频\n')
            return 4
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        # 桥给的是 .mp3 路径；统一转成 mp3，NapCat 那边再转 silk
        r = subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(tmp),
             '-codec:a', 'libmp3lame', '-q:a', '4', a.out],
            capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write('转 mp3 失败：%s\n' % (r.stderr or '').strip()[:300])
            return 5
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
