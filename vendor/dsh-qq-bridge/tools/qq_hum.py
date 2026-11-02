#!/usr/bin/env python3
"""哼一段 → 量成简谱 → 存进曲目表（~/.dsh/qq-sing/melodies.json）。

为什么要有这个：DiffSinger 只能照着**音符**唱，而「某首歌的调子」这件事，
模型凭记忆写简谱经常是错的（2026-10-31《爱你》就是这么翻车的）。
最可靠的音高来源是**人**：让人哼一遍，这里把音高和时长量出来。

用法：
    python qq_hum.py --in hum.wav                       # 只量，stdout 打一行 JSON
    python qq_hum.py --in hum.wav --song 孤勇者 --save  # 存进曲目表（先备份原文件）

退出码：0 = 量出来了（哪怕带警告）；非 0 = 没量出来（stderr 里是原因）。
"""
import argparse
import json
import math
import shutil
import sys
from datetime import date
from pathlib import Path

# 认定「一个音」的门槛
音高容忍 = 0.7          # 同一个音里允许的半音起伏；超了就当换音
最短音秒 = 0.11         # 比这短的当噪音丢掉（清嗓、气声、换气）
持续帧 = 4              # 换音要「连着这么多帧」才认 —— 不然音之间的滑音会被切成假音
合并间隔秒 = 0.12       # 同音高、间隔比这短的两段并成一个
音节拍 = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]


def 找音谷(rms, 窗=13, 比=0.5):
    """音量坑：两边都响、自己明显掉下去的那些帧。

    「一闪一闪」这种**连着两个同音高**的字，音高一路没变，只有音量坑能分开它们。
    用相对判据（比旁边低一半）而不是绝对阈值 —— 哼唱有轻有响，绝对阈值会把
    轻的地方全判成坑。窗 ±13 帧 ≈ ±150ms。
    """
    import numpy as np

    n = len(rms)
    谷 = np.zeros(n, dtype=bool)
    for k in range(2, n - 2):
        左 = rms[max(0, k - 窗):k]
        右 = rms[k + 1:k + 1 + 窗]
        if 左.size == 0 or 右.size == 0:
            continue
        周 = min(float(左.max()), float(右.max()))
        if 周 <= 0:
            continue
        if rms[k] < 比 * 周 and rms[k] <= float(rms[max(0, k - 2):k + 3].min()):
            谷[k] = True
    return 谷


def 中值滤波(midi, 核=5):
    """先给音高曲线去毛刺：一两个帧的尖刺（pyin 在音与音之间偶尔冒出来的假音高）
    会被中值抹掉，真正的换音（连着好几帧）留得住。"""
    import numpy as np

    n = len(midi)
    出 = midi.copy()
    半 = 核 // 2
    for k in range(n):
        w = midi[max(0, k - 半):k + 半 + 1]
        w = w[~np.isnan(w)]
        if w.size:
            出[k] = float(np.median(w))
    return 出


def 切段(midi, 有声, 帧秒, 谷=None):
    """按音高 + 起音把帧切成一个个音。

    ⚠️ 2026-11-01：一开始是「一帧偏离就换音」，结果每个音前后都多出两三个
    滑音碎音（pyin 的分析窗 ~90ms，音与音之间的过渡被量成中间音高）。
    现在要求偏离**连续持续几帧**才认新音，滑音就归到前一个音里去了。
    ⚠️ 光看音高还不够：连着唱两个**同音高**的字（「一闪一闪」）时，pyin 一路都
    是同一个音高、中间不断 —— 得靠音量坑（谷）把它分开。
    """
    import numpy as np

    断 = lambda k: (not 有声[k]) or math.isnan(midi[k]) or bool(谷[k])  # noqa: E731
    段 = []
    i, n = 0, len(midi)
    while i < n:
        if 断(i):
            i += 1
            continue
        起 = i
        本音 = [float(midi[i])]
        i += 1
        候选 = []
        while i < n:
            if 断(i):                            # 无声 / 音量坑
                断起 = i
                是坑 = bool(谷[i])
                while i < n and 断(i) and (i - 断起) < 4:
                    if 谷[i]:
                        是坑 = True
                    i += 1
                if i < n and not 是坑:            # 只断开了一下下（换气、辅音）→ 还算同一个音
                    本音.append(float(midi[i]))
                    i += 1
                    continue
                break
            当前 = float(np.median(本音[-min(len(本音), 8):]))
            if abs(float(midi[i]) - 当前) > 音高容忍:
                候选.append(i)
                if len(候选) >= 持续帧:
                    近 = [float(midi[k]) for k in 候选[-持续帧:]]
                    if max(近) - min(近) <= 音高容忍:      # 稳住了 → 真的是新音
                        段.append((起, 候选[0] - 1 if 候选[0] > 起 else 起))
                        起 = 候选[0]
                        本音 = [float(midi[k]) for k in 候选]
                        候选 = []
                i += 1
                continue
            本音.extend(float(midi[k]) for k in 候选)  # 又转回去了：那些帧算旧音
            候选 = []
            本音.append(float(midi[i]))
            i += 1
        if 候选:
            本音.extend(float(midi[k]) for k in 候选)
        if i - 1 >= 起:
            段.append((起, i - 1))
    # 太短的段丢掉
    return [(a, b) for a, b in 段 if (b - a + 1) * 帧秒 >= 最短音秒]


def 量旋律(路径, bpm覆盖=0.0):
    import librosa
    import numpy as np

    y, sr = librosa.load(str(路径), sr=22050, mono=True)
    if y.size < sr * 0.4:
        raise SystemExit('音频太短（%.1f 秒），哼一句至少一两秒' % (y.size / sr))
    try:
        y, _ = librosa.effects.trim(y, top_db=30)
    except Exception:
        pass
    if y.size < sr * 0.3:
        raise SystemExit('这段里没听到声音')

    f0, 有声, _ = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C6'),
                               sr=sr, frame_length=2048, hop_length=256)
    midi = 中值滤波(librosa.hz_to_midi(f0))
    帧秒 = 256.0 / sr

    # 能量：连着唱两个同音高的字时，只有音量坑能把它们分开
    rms = librosa.feature.rms(y=y, frame_length=512, hop_length=256, center=True)[0]
    if rms.size != len(midi):
        rms = np.resize(rms, len(midi))
    谷 = 找音谷(rms)

    # ① 按「音高稳不稳 + 有没有断」切段
    段 = 切段(midi, 有声, 帧秒, 谷)

    # ② 音高取「中段」的中位数（避开起音滑上去、收尾掉下来）；
    #    时长按「前后两段的中点」算 —— pyin 的分析窗约 90ms，音与音的交界处两头都不认，
    #    直接用段的起止会把每个音都量短一截（实测 0.6 秒的音只量到 0.3 秒）。
    音符 = []
    for i, (a, b) in enumerate(段):
        边 = max(1, int((b - a + 1) * 0.2))
        sel = midi[a + 边:b + 1 - 边]
        sel = sel[~np.isnan(sel)]
        if sel.size == 0:
            continue
        原长 = (b - a + 1) * 帧秒           # 段本身有多长（会被分析窗削短，但判断滑音要看它）
        前尾 = 段[i - 1][1] if i > 0 else a
        后起 = 段[i + 1][0] if i + 1 < len(段) else b
        起 = float(a) if i == 0 else (前尾 + a) / 2.0
        尾 = float(b) if i + 1 >= len(段) else (b + 后起) / 2.0
        整段 = midi[a:b + 1]
        整段 = 整段[~np.isnan(整段)]
        音符.append([float(np.median(sel)), max(0.0, (尾 - 起) * 帧秒), 原长, (a - 前尾) * 帧秒,
                    float(np.std(整段)) if 整段.size else 0.0])
    if len(音符) < 2:
        raise SystemExit('只量到一个音 —— 哼一句完整点的旋律（最好带歌词）')

    # ③ 并碎段：只并「本来就是一个音、被颤音/换气切碎」的那种 ——
    #   前提是**前一小段很短**（< 0.15 秒）。不加这个前提就会把「一闪一闪」这种
    #   连着两个同音高的字又并回一个音（那是两个音，不是碎片）。
    并 = [音符[0]]
    for m, d, 原, 隔, 稳 in 音符[1:]:
        上 = 并[-1]
        if abs(上[0] - m) < 0.5 and 隔 < 0.06 and 上[1] < 0.15:
            上[1] += d
            上[2] += 原
            上[4] = max(上[4], 稳)
        else:
            并.append([m, d, 原, 隔, 稳])
    音符 = [[m, d, 原, 稳] for m, d, 原, _, 稳 in 并]

    # ④ 滑音假音：又短、音高又夹在前后两个音中间的那一段，是过渡不是音。
    #   看**段本身**的长度（原）而不是补过中点的长度 —— 补完会把滑音补长，就漏掉了。
    #   开头/结尾那种一冒头就没的，也是起音滑上去的那一下，一并丢掉。
    净 = []
    for i, (m, d, 原, 稳) in enumerate(音符):
        if 原 < 0.18:
            if 0 < i < len(音符) - 1:
                前, 后 = 音符[i - 1][0], 音符[i + 1][0]
                if min(前, 后) - 0.3 <= m <= max(前, 后) + 0.3:
                    continue
            elif len(音符) >= 5 and (i == 0 or i == len(音符) - 1) and 原 < 0.15:
                continue
        净.append([m, d, 稳])
    音符 = 净
    稳中位 = float(np.median([稳 for _, _, 稳 in 音符])) if 音符 else 0.0

    # ⑤ 八度归位：只整体挪八度，不动音程 —— 哼低了唱出来会像大叔
    中位音 = float(np.median([m for m, _, _ in 音符]))
    挪 = 0
    while 中位音 + 挪 < 57:      # A3
        挪 += 12
    while 中位音 + 挪 > 69:      # A4
        挪 -= 12

    # ⑥ 定速度、把时长量化成拍
    if bpm覆盖 and float(bpm覆盖) > 0:
        bpm = float(bpm覆盖)
    else:
        基准 = float(np.median([d for _, d, _ in 音符]))
        bpm = 60.0 / 基准 if 基准 > 0 else 100.0
        bpm = max(60.0, min(160.0, round(bpm)))
    拍秒 = 60.0 / bpm

    出 = []
    for m, d, _ in 音符:
        midi整 = int(round(m + 挪))
        拍 = max(0.25, min(4.0, round(d / 拍秒 / 0.25) * 0.25))
        if 拍 not in 音节拍:
            拍 = min(音节拍, key=lambda x: abs(x - 拍))
        出.append('%s:%s' % (librosa.midi_to_note(midi整, unicode=False), ('%g' % 拍)))

    # ⑦ 像不像「在唱」：说话的音高在字里就一直在滑（段内 std 大），唱的音是稳的。
    #   实测：哼唱 0.09～0.29 半音，说话 0.58～0.60 —— 0.45 分开。
    警告 = ''
    if 稳中位 > 0.45:
        警告 = '音高一直在滑（每段 ±%.1f 半音），听着更像说话 —— 哼的时候每个音唱稳一点' % 稳中位
    if len(出) < 4:
        警告 = 警告 or '只量到 %d 个音，可能哼得太短' % len(出)
    音域 = '%s~%s' % (min(出, key=lambda s: librosa.note_to_midi(s.split(':')[0])).split(':')[0],
                      max(出, key=lambda s: librosa.note_to_midi(s.split(':')[0])).split(':')[0])
    return {
        'ok': True, 'bpm': bpm, 'notes': 出, '个数': len(出), '音域': 音域,
        '秒数': round(float(len(y)) / sr, 2), '稳定度': round(稳中位, 2), '警告': 警告,
    }


def 存曲目(量, 歌名, 歌词='', 文件=None):
    路径 = Path(文件) if 文件 else (Path.home() / '.dsh' / 'qq-sing' / 'melodies.json')
    路径.parent.mkdir(parents=True, exist_ok=True)
    try:
        原 = json.loads(路径.read_text(encoding='utf-8')) if 路径.exists() else {}
        if not isinstance(原, dict):
            原 = {}
    except Exception as e:  # noqa: BLE001
        raise SystemExit('melodies.json 现在的读不了（%s），先修好再存' % e)
    if 路径.exists():
        shutil.copyfile(路径, str(路径) + '.bak')
    条目 = {'bpm': 量['bpm'], 'notes': 量['notes'], '来源': '哼唱', '学时': date.today().isoformat()}
    if 歌词:
        条目['lyrics'] = 歌词
    elif isinstance(原.get(歌名), dict) and 原[歌名].get('lyrics'):
        条目['lyrics'] = 原[歌名]['lyrics']
    原[歌名] = 条目
    路径.write_text(json.dumps(原, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 路径


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='来源', required=True, help='哼唱的音频（wav/mp3/m4a 都行）')
    ap.add_argument('--song', default='', help='歌名；配上 --save 就是存进曲目表用的名字')
    ap.add_argument('--lyrics', default='', help='可选：这首歌的歌词（存进曲目表，能按歌词自动认歌）')
    ap.add_argument('--bpm', type=float, default=0, help='可选：指定速度，不填自己估')
    ap.add_argument('--save', action='store_true', help='写进曲目表（同名覆盖，先备份 .bak）')
    ap.add_argument('--melodies', default='', help='曲目表路径，默认 ~/.dsh/qq-sing/melodies.json')
    a = ap.parse_args()

    if not Path(a.来源).exists():
        raise SystemExit('找不到音频：%s' % a.来源)
    量 = 量旋律(a.来源, a.bpm)
    if a.save:
        if not a.song.strip():
            raise SystemExit('要 --save 就得给 --song 歌名')
        量['存到'] = str(存曲目(量, a.song.strip(), a.lyrics.strip(), a.melodies or None))
    print(json.dumps(量, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
