#!/usr/bin/env python3
"""大肥鱼 RVC 换声（说话 + 翻唱共用）。

跑在 ~/.dsh/qq-rvc/.venv 里（infer_rvc_python + torch），权重都在本地：
  <rvc-home>/models/dafeiyu-singing-rvc-v1.pth
  <rvc-home>/models/dafeiyu-singing-rvc-v1.index
  <rvc-home>/models/rmvpe.pt
  <rvc-home>/hubert_base/{config.json,pytorch_model.bin}

用法：
  python qq_rvc.py --input in.wav --output out.wav --pitch 0
  python qq_rvc.py --input tts.mp3 --output voice.wav --pitch 0
  python qq_rvc.py --input vocals.wav --output sing.wav --pitch 12

男声原曲升八度用 --pitch 12；女声区素材用 0。
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

家 = Path(os.environ.get('DSH_HOME') or (Path.home() / '.dsh'))
默认RVC家 = 家 / 'qq-rvc'


def 跑(命令, 超时=120):
    print('+ ' + ' '.join(str(x) for x in 命令), file=sys.stderr)
    try:
        return subprocess.run(命令, capture_output=True, text=True, timeout=超时)
    except FileNotFoundError as e:
        raise SystemExit('找不到命令：%s（%s）' % (命令[0], e))
    except subprocess.TimeoutExpired:
        raise SystemExit('命令超时（%ss）：%s' % (超时, ' '.join(str(x) for x in 命令)))


def 必须(结果, 说明):
    if 结果.returncode != 0:
        尾 = (结果.stderr or 结果.stdout or '').strip()[-800:]
        raise SystemExit('%s失败（退出码 %s）：%s' % (说明, 结果.returncode, 尾))
    return 结果


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--rvc-home', default=str(默认RVC家))
    ap.add_argument('--model', default='')
    ap.add_argument('--index', default='')
    ap.add_argument('--pitch', type=int, default=0)
    ap.add_argument('--index-rate', type=float, default=0.25)
    ap.add_argument('--protect', type=float, default=0.33)
    ap.add_argument('--envelope', type=float, default=0.5)
    ap.add_argument('--f0-method', default='rmvpe+')
    ap.add_argument('--fp32', action='store_true', help='关闭半精度；更干净但更慢')
    ap.add_argument('--device', default='cuda:0')
    a = ap.parse_args()

    RVC家 = Path(a.rvc_home).expanduser()
    输入 = Path(a.input).expanduser()
    输出 = Path(a.output).expanduser()
    模型 = Path(a.model).expanduser() if a.model else RVC家 / 'models' / 'dafeiyu-singing-rvc-v1.pth'
    索引 = Path(a.index).expanduser() if a.index else RVC家 / 'models' / 'dafeiyu-singing-rvc-v1.index'
    胡伯特 = RVC家 / 'hubert_base'
    RMVPE = RVC家 / 'models' / 'rmvpe.pt'
    if not 输入.exists():
        raise SystemExit('输入不存在：%s' % 输入)
    if not 模型.exists():
        raise SystemExit('RVC 模型不存在：%s' % 模型)
    if not 索引.exists():
        raise SystemExit('RVC 索引不存在：%s' % 索引)
    if not (胡伯特 / 'config.json').exists():
        raise SystemExit('HuBERT 没准备好：%s' % 胡伯特)
    if not RMVPE.exists():
        raise SystemExit('RMVPE 没准备好：%s' % RMVPE)

    # 本地权重齐全，不需要联网；把 socks 代理摘掉，免得 httpx 初始化失败。
    os.environ['HF_HUB_OFFLINE'] = '1'
    for k in ('ALL_PROXY', 'all_proxy'):
        os.environ.pop(k, None)

    临时 = Path(tempfile.mkdtemp(prefix='qq-rvc-', dir=str(RVC家)))
    try:
        if 输入.suffix.lower() == '.wav':
            音频 = 输入
        else:
            音频 = 临时 / 'input.wav'
            必须(跑(['ffmpeg', '-y', '-i', str(输入), '-vn', '-ac', '1', '-ar', '44100',
                     '-c:a', 'pcm_s16le', str(音频)], 60), '转 wav')

        from infer_rvc_python import BaseLoader

        转换器 = BaseLoader(
            only_cpu=(a.device == 'cpu'),
            hubert_path=str(胡伯特),
            rmvpe_path=str(RMVPE),
        )
        if a.fp32:
            转换器.config.is_half = False
        转换器.apply_conf(
            tag='dafeiyu',
            file_model=str(模型),
            pitch_algo=a.f0_method,
            pitch_lvl=int(a.pitch),
            file_index=str(索引),
            index_influence=float(a.index_rate),
            respiration_median_filtering=3,
            envelope_ratio=float(a.envelope),
            consonant_breath_protection=float(a.protect),
        )
        结果 = 转换器(str(音频), 'dafeiyu', overwrite=True, parallel_workers=1)
        if isinstance(结果, (list, tuple)):
            结果 = 结果[0] if 结果 else ''
        结果 = str(结果 or '')
        if not 结果 or not Path(结果).exists():
            raise SystemExit('RVC 没产出文件：%r' % (结果,))
        输出.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(结果, 输出)
        print('OK %s' % 输出, file=sys.stderr)
        return 0
    finally:
        shutil.rmtree(临时, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
