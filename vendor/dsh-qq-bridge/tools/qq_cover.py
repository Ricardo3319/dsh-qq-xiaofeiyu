#!/usr/bin/env python3
"""点歌 → AI 翻唱：原曲下载 / 切片 → 分离人声 → 零样本换声 → 混伴奏。

给 dsh-qq-bridge 的「翻唱」工具用。目标：用户点一首具体的歌时，
不用简谱，直接拿原曲的旋律，把歌声换成小肥鱼/胡桃的音色。

依赖（都在 ~/.dsh/qq-cover 里，不进本仓库）：
  ~/.dsh/qq-cover/.venv            torch 2.4 + demucs + yt-dlp
  ~/.dsh/qq-cover/seed-vc          Seed-VC（GPL-3.0，独立进程调用）
  ~/.dsh/qq-cover/ref/hutao_ref.wav  目标音色参考（1–30 秒唱歌/说话）

用法：
  python qq_cover.py --song "孤勇者 陈奕迅" --out /tmp/cover.wav
  python qq_cover.py --audio /path/to/song.mp3 --start 30 --duration 45 --out /tmp/cover.wav

注意：只用于个人试听。原曲、声库和 Seed-VC 的授权各自独立；
不要把下载的歌曲、模型权重或转换结果提交进仓库。
"""
import argparse
import hashlib
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

家 = Path(os.environ.get('DSH_HOME') or (Path.home() / '.dsh'))
默认翻唱家 = 家 / 'qq-cover'


def 跑(命令, cwd=None, 超时=300, 环境=None, 去掉=()):
    """跑一个外部命令；返回 CompletedProcess，失败时把 stderr 带进异常。"""
    print('+ ' + ' '.join(str(x) for x in 命令), file=sys.stderr)
    实环境 = {k: v for k, v in os.environ.items() if k not in 去掉}
    if 环境:
        实环境.update(环境)
    try:
        return subprocess.run(命令, cwd=str(cwd) if cwd else None, env=实环境,
                              capture_output=True, text=True, timeout=超时)
    except FileNotFoundError as e:
        raise SystemExit('找不到命令：%s（%s）' % (命令[0], e))
    except subprocess.TimeoutExpired:
        raise SystemExit('命令超时（%ss）：%s' % (超时, ' '.join(str(x) for x in 命令)))


def 必须(结果, 说明):
    if 结果.returncode != 0:
        尾 = (结果.stderr or 结果.stdout or '').strip()[-800:]
        raise SystemExit('%s失败（退出码 %s）：%s' % (说明, 结果.returncode, 尾))
    return 结果


def 找工具(名, 翻唱家):
    for p in (Path(sys.executable).parent / 名, 翻唱家 / '.venv' / 'bin' / 名, Path.home() / '.local' / 'bin' / 名):
        if p.exists():
            return str(p)
    p = shutil.which(名)
    if p:
        return p
    raise SystemExit('没装 %s（应该在 %s/.venv/bin）' % (名, 翻唱家))


def 下载(歌曲, 临时, 翻唱家, 站点):
    """歌名或 URL → 本地 wav。B 站搜索用 bilisearch1:，YouTube 用 ytsearch1:。"""
    ytdlp = 找工具('yt-dlp', 翻唱家)
    if 歌曲.startswith('http://') or 歌曲.startswith('https://'):
        目标 = 歌曲
    elif 站点 == 'youtube':
        目标 = 'ytsearch1:' + 歌曲
    else:
        目标 = 'bilisearch1:' + 歌曲
    模板 = str(临时 / 'source.%(ext)s')
    基 = [ytdlp, '--no-playlist', '-f', 'bestaudio/best', '-x',
          '--audio-format', 'wav', '--audio-quality', '0', '-o', 模板]
    结果 = 跑(基 + [目标], 超时=240)
    if 结果.returncode != 0 and 站点 != 'youtube' and not 歌曲.startswith('http'):
        # B 站偶尔要登录/风控；改 YouTube 搜索再试一次（走 Clash）
        print('B 站下载失败，改用 YouTube 搜索再试', file=sys.stderr)
        结果 = 跑(基 + ['ytsearch1:' + 歌曲], 超时=240)
    if 结果.returncode != 0:
        尾 = (结果.stderr or '').strip()[-800:]
        raise SystemExit('下载失败：%s' % 尾)
    候选 = sorted(临时.glob('source.*'))
    if not 候选:
        raise SystemExit('下载完了但没找到 source.*')
    音频 = 候选[0]
    if 音频.suffix.lower() != '.wav':
        转 = 跑(['ffmpeg', '-y', '-i', str(音频), '-vn', '-ac', '2', '-ar', '44100',
                str(临时 / 'source.wav')], 超时=120)
        必须(转, '转 wav')
        音频 = 临时 / 'source.wav'
    return 音频


def 切片(音频, 临时, 起始, 时长):
    出 = 临时 / 'clip.wav'
    结果 = 跑(['ffmpeg', '-y', '-ss', '%.2f' % 起始, '-t', '%.2f' % 时长,
              '-i', str(音频), '-vn', '-ac', '2', '-ar', '44100', str(出)], 超时=120)
    必须(结果, '切片')
    return 出


def 分离(片段, 临时, 翻唱家):
    demucs = 找工具('demucs', 翻唱家)
    输出 = 临时 / 'separated'
    基 = [demucs, '--two-stems=vocals', '-n', 'htdemucs', '--segment', '5',
          '--out', str(输出), str(片段)]
    结果 = 跑(基, cwd=临时, 超时=420)
    if 结果.returncode != 0 and 'out of memory' in (结果.stderr or '').lower():
        print('显存不够，Demucs 退回 CPU（会慢一些）', file=sys.stderr)
        结果 = 跑([demucs, '-d', 'cpu'] + 基[1:], cwd=临时, 超时=600)
    必须(结果, '分离人声')
    目录 = 输出 / 'htdemucs' / 片段.stem
    人声 = 目录 / 'vocals.wav'
    伴奏 = 目录 / 'no_vocals.wav'
    if not 人声.exists():
        raise SystemExit('Demucs 没产出 vocals.wav（%s）' % 目录)
    return 人声, (伴奏 if 伴奏.exists() else None)


def 估计音高(文件, 秒=20.0):
    """量一段音频的中位基频（Hz）。只用来决定移调，不参与换声。"""
    import numpy as np
    import librosa
    y, sr = librosa.load(str(文件), sr=16000, mono=True, duration=秒)
    if len(y) < sr // 2:
        return 0.0
    f0, _, _ = librosa.pyin(y, fmin=65, fmax=1000, sr=sr, frame_length=2048)
    v = f0[np.isfinite(f0)]
    return float(np.median(v)) if len(v) else 0.0


def 自动移调(人声, 参考):
    """把源人声的整体音高挪到参考音色附近。

    只按**八度**移（0 / ±12）：伴奏没有跟着移调，按半音硬挪会把歌声挪到
    别的调上，跟伴奏打架，听起来就是「跑调」。男声原曲升一个八度既保留原调，
    又能离开「低音炮」；本来就在女声区的歌算出来是 0，不会被硬拔高。
    """
    a = 估计音高(人声)
    b = 估计音高(参考)
    if a <= 0 or b <= 0:
        print('音高量不出来，移调按 0 处理', file=sys.stderr)
        return 0
    n = 12 * int(round(math.log2(b / a)))
    n = max(-12, min(12, n))
    print('音高：源 %.1fHz / 参考 %.1fHz → 移调 %+d 半音（八度对齐）' % (a, b, n), file=sys.stderr)
    return n


def 全曲移调(人声, 目标=270.0, 最多=3):
    """整首歌一起移调，保证人声和伴奏还在同一个调上。

    用户 2026-11-11 定的：**最多 +2~+3**，不刻意拔高——拉太高会破音（+9 实测）。
    按源人声中位音高选移调量：往上最多 `最多` 个半音，往下最多 6 个半音
    （太尖的女声源可以降）。人声用 RVC 的 --pitch 移，伴奏用 rubberband 移
    同样的量，保证同调。
    """
    a = 估计音高(人声)
    if a <= 0:
        print('音高量不出来，整曲移调按 0 处理', file=sys.stderr)
        return 0
    n = int(round(12 * math.log2(目标 / a)))
    n = max(-6, min(int(最多), n))
    print('整曲移调：源 %.1fHz / 目标 %.1fHz → %+d 半音（上限 +%d）' % (a, 目标, n, int(最多)), file=sys.stderr)
    return n


def 移调伴奏(伴奏, 临时, n):
    """只移伴奏；人声交给 RVC 的 --pitch，人声的咬字比 rubberband 预移清楚。"""
    if not n or not 伴奏 or not 伴奏.exists():
        return 伴奏
    比 = 2 ** (n / 12.0)
    出 = 临时 / 'inst_shift.wav'
    结果 = 跑(['ffmpeg', '-y', '-i', str(伴奏), '-af',
              'rubberband=pitch=%.6f:formant=preserved' % 比,
              '-ar', '44100', str(出)], 超时=120)
    必须(结果, '伴奏移调')
    return 出


def 选段(音频, 取长):
    """自动挑一段：副歌前几句主歌 + 副歌。

    不靠歌名/歌词，只看整首的短时能量：跳过开头 15 秒，找第一个持续 5 秒
    超过 85 分位的响度段（通常就是副歌），从它前 12 秒开始切，45 秒正好
    覆盖「副歌前几句 + 副歌」。找不到就退到全曲 20% 处。
    """
    import numpy as np
    import librosa
    y, sr = librosa.load(str(音频), sr=22050, mono=True, duration=240)
    if len(y) < sr * 20:
        return 0.0
    rms = librosa.feature.rms(y=y, frame_length=sr * 2, hop_length=sr)[0]
    if len(rms) < 10:
        return 0.0
    sm = np.convolve(rms, np.ones(3) / 3, mode='same')
    lo = min(15, len(sm) - 1)
    thr = float(np.percentile(sm[lo:], 85))
    win = 5
    for i in range(lo, max(lo + 1, len(sm) - win)):
        if float(np.mean(sm[i:i + win])) >= thr:
            start = max(0.0, i - 12.0)
            start = min(start, max(0.0, len(y) / sr - 取长))
            print('自动选段：%.1fs 起（能量阈值 %.5f）' % (start, thr), file=sys.stderr)
            return start
    start = max(0.0, len(y) / sr * 0.2)
    print('自动选段：没找到明显副歌，按 20%% 起（%.1fs）' % start, file=sys.stderr)
    return start


def 换声(人声, 参考, 临时, 翻唱家, 步数, 自动f0, 移调):
    seed_vc = 翻唱家 / 'seed-vc'
    解释器 = 翻唱家 / '.venv' / 'bin' / 'python'
    if not (seed_vc / 'inference.py').exists():
        raise SystemExit('Seed-VC 没装好：%s' % seed_vc)
    if not 参考.exists():
        raise SystemExit('参考音不存在：%s' % 参考)
    输出 = 临时 / 'vc'
    命令 = [str(解释器), 'inference.py', '--source', str(人声), '--target', str(参考),
            '--output', str(输出), '--f0-condition', 'True',
            '--diffusion-steps', str(步数), '--fp16', 'True']
    if 自动f0:
        命令 += ['--auto-f0-adjust', 'True']
    if 移调:
        命令 += ['--semi-tone-shift', str(移调)]
    # 2026-11-10 实测：HF 大文件（RMVPE / BigVGAN / Whisper）下载不稳；
    # 权重放在 qq-cover 本地目录，推理时直接指过去，不再联网下载。
    环境 = {'HF_HUB_DISABLE_XET': '1', 'HF_HUB_ENABLE_HF_TRANSFER': '0'}
    for 键, 子目录, 必需 in [
        ('SEED_VC_BIGVGAN_DIR', 'bigvgan', 'bigvgan_generator.pt'),
        ('SEED_VC_WHISPER_DIR', 'whisper-small', 'model.safetensors'),
    ]:
        目录 = 翻唱家 / 子目录
        if (目录 / 必需).exists():
            环境[键] = str(目录)
    结果 = 跑(命令, cwd=seed_vc, 超时=420, 环境=环境)
    必须(结果, 'Seed-VC 换声')
    候选 = sorted(输出.glob('*.wav'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not 候选:
        raise SystemExit('Seed-VC 没产出 wav（%s）' % 输出)
    return 候选[0]


def 换声_rvc(人声, 临时, rvc_home, 解释器, 脚本, 模型, 索引, 移调, 索引率):
    for 名, p in [('RVC 解释器', 解释器), ('RVC 脚本', 脚本), ('RVC 模型', 模型), ('RVC 索引', 索引)]:
        if not Path(p).exists():
            raise SystemExit('%s不存在：%s' % (名, p))
    输出 = 临时 / 'rvc.wav'
    命令 = [str(解释器), str(脚本), '--input', str(人声), '--output', str(输出),
            '--rvc-home', str(rvc_home), '--model', str(模型), '--index', str(索引),
            '--pitch', str(移调), '--index-rate', str(索引率)]
    结果 = 跑(命令, 超时=300, 环境={'HF_HUB_OFFLINE': '1'},
              去掉=('ALL_PROXY', 'all_proxy'))
    必须(结果, 'RVC 换声')
    if not 输出.exists():
        raise SystemExit('RVC 没产出 wav：%s' % 输出)
    return 输出


def 混音(换声后, 伴奏, 出):
    出.parent.mkdir(parents=True, exist_ok=True)
    if 伴奏 and 伴奏.exists():
        # 人声抬 1.35、伴奏压到 0.85；高通去闷、低通去「沙沙」，限幅防削波。
        滤镜 = ('[0:a]highpass=f=70,lowpass=f=16000,volume=1.35[v];[1:a]volume=0.85[i];'
                '[v][i]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95')
        结果 = 跑(['ffmpeg', '-y', '-i', str(换声后), '-i', str(伴奏),
                  '-filter_complex', 滤镜, '-ac', '2', '-ar', '44100', str(出)], 超时=180)
        必须(结果, '混音')
    else:
        shutil.copyfile(换声后, 出)


def 缓存键(歌曲, 音频, 起始, 时长, 参考, 步数, 移调, 引擎='seedvc', 模型='', 索引='', 索引率=0.0):
    h = hashlib.sha256()
    h.update(b'cover-v6')  # 算法变了就换版本号，旧缓存自然失效
    h.update(str(歌曲 or '').encode())
    h.update(str(起始).encode())
    h.update(str(时长).encode())
    h.update(str(步数).encode())
    h.update(('shift:%s' % 移调).encode())
    h.update(('engine:%s' % 引擎).encode())
    if 引擎 == 'rvc':
        h.update(('rvc-rate:%s' % 索引率).encode())
        for p in (模型, 索引):
            p = Path(p) if p else None
            if p and p.exists():
                st = p.stat()
                h.update(('%s:%s:%s' % (p, st.st_size, int(st.st_mtime))).encode())
    if 音频 and 音频.exists():
        st = 音频.stat()
        h.update(('%s:%s:%s' % (音频, st.st_size, int(st.st_mtime))).encode())
    if 参考 and 参考.exists():
        st = 参考.stat()
        h.update(('%s:%s:%s' % (参考, st.st_size, int(st.st_mtime))).encode())
    return h.hexdigest()[:24]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--song', default='', help='歌名（B 站搜索）或视频 URL')
    ap.add_argument('--audio', default='', help='本地音频；给了就不下载')
    ap.add_argument('--out', required=True)
    ap.add_argument('--start', type=float, default=None,
                    help='从第几秒开始；不填自动选副歌前几句主歌+副歌')
    ap.add_argument('--duration', type=float, default=45.0, help='取多长，默认 45 秒')
    ap.add_argument('--ref', default='', help='目标音色参考 wav（Seed-VC 用）')
    ap.add_argument('--engine', choices=['seedvc', 'rvc'], default='rvc',
                    help='换声引擎：rvc（大肥鱼，默认）或 seedvc（旧）')
    ap.add_argument('--rvc-home', default=str(家 / 'qq-rvc'))
    ap.add_argument('--rvc-python', default='', help='留空 = <rvc-home>/.venv/bin/python')
    ap.add_argument('--rvc-script', default='', help='留空 = 本目录的 qq_rvc.py')
    ap.add_argument('--rvc-model', default='', help='留空 = <rvc-home>/models/dafeiyu-singing-rvc-v1.pth')
    ap.add_argument('--rvc-index', default='', help='留空 = <rvc-home>/models/dafeiyu-singing-rvc-v1.index')
    ap.add_argument('--rvc-index-rate', type=float, default=0.25)
    ap.add_argument('--rvc-pitch', type=int, default=None, help='RVC 移调；不填按八度自动算')
    ap.add_argument('--cover-home', default=str(默认翻唱家))
    ap.add_argument('--site', choices=['bilibili', 'youtube'], default='bilibili')
    ap.add_argument('--steps', type=int, default=50)
    ap.add_argument('--semi-tone-shift', type=int, default=None,
                    help='移调半音；不填按源/参考音高自动算（最多 ±12）')
    ap.add_argument('--auto-f0-adjust', action='store_true')
    ap.add_argument('--no-cache', action='store_true')
    ap.add_argument('--keep-temp', action='store_true')
    a = ap.parse_args()

    翻唱家 = Path(a.cover_home).expanduser()
    参考 = Path(a.ref).expanduser() if a.ref else 翻唱家 / 'ref' / 'hutao_ref.wav'
    RVC家 = Path(a.rvc_home).expanduser()
    RVC解释器 = Path(a.rvc_python).expanduser() if a.rvc_python else RVC家 / '.venv' / 'bin' / 'python'
    RVC脚本 = Path(a.rvc_script).expanduser() if a.rvc_script else Path(__file__).resolve().parent / 'qq_rvc.py'
    RVC模型 = Path(a.rvc_model).expanduser() if a.rvc_model else RVC家 / 'models' / 'dafeiyu-singing-rvc-v1.pth'
    RVC索引 = Path(a.rvc_index).expanduser() if a.rvc_index else RVC家 / 'models' / 'dafeiyu-singing-rvc-v1.index'
    if not a.song and not a.audio:
        raise SystemExit('要么给 --song，要么给 --audio')
    if a.audio and not Path(a.audio).exists():
        raise SystemExit('本地音频不存在：%s' % a.audio)
    if a.engine == 'seedvc' and not 参考.exists():
        raise SystemExit('参考音不存在：%s' % 参考)
    a.duration = max(10.0, min(float(a.duration), 75.0))
    起始键 = 'auto' if a.start is None else max(0.0, float(a.start))

    缓存目录 = 翻唱家 / 'cache'
    缓存目录.mkdir(parents=True, exist_ok=True)
    移调键 = ('auto' if a.rvc_pitch is None else a.rvc_pitch) if a.engine == 'rvc' \
        else ('auto' if a.semi_tone_shift is None else a.semi_tone_shift)
    键 = 缓存键(a.song or a.audio, Path(a.audio) if a.audio else None,
             起始键, a.duration, 参考 if a.engine == 'seedvc' else None, a.steps,
             移调键, a.engine,
             str(RVC模型) if a.engine == 'rvc' else '',
             str(RVC索引) if a.engine == 'rvc' else '',
             a.rvc_index_rate)
    缓存 = 缓存目录 / (键 + '.wav')
    if 缓存.exists() and not a.no_cache:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(缓存, a.out)
        print('CACHE %s' % a.out, file=sys.stderr)
        return 0

    临时 = Path(tempfile.mkdtemp(prefix='qq-cover-', dir=str(翻唱家)))
    try:
        if a.audio:
            音频 = Path(a.audio)
        else:
            音频 = 下载(a.song, 临时, 翻唱家, a.site)
        if a.start is None:
            a.start = 选段(音频, a.duration)
        else:
            a.start = max(0.0, float(a.start))
        片段 = 切片(音频, 临时, a.start, a.duration)
        人声, 伴奏 = 分离(片段, 临时, 翻唱家)
        if a.engine == 'rvc':
            移调 = 全曲移调(人声, 最多=3) if a.rvc_pitch is None \
                else max(-12, min(12, int(a.rvc_pitch)))
            伴奏 = 移调伴奏(伴奏, 临时, 移调)
            换声后 = 换声_rvc(人声, 临时, RVC家, RVC解释器, RVC脚本,
                            RVC模型, RVC索引, 移调, a.rvc_index_rate)
        else:
            移调 = 自动移调(人声, 参考) if a.semi_tone_shift is None \
                else max(-24, min(24, int(a.semi_tone_shift)))
            换声后 = 换声(人声, 参考, 临时, 翻唱家, a.steps, a.auto_f0_adjust, 移调)
        最终 = 临时 / 'final.wav'
        混音(换声后, 伴奏, 最终)
        shutil.copyfile(最终, 缓存)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(最终, a.out)
        print('OK %s' % a.out, file=sys.stderr)
        return 0
    finally:
        if a.keep_temp:
            print('临时目录保留：%s' % 临时, file=sys.stderr)
        else:
            shutil.rmtree(临时, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
