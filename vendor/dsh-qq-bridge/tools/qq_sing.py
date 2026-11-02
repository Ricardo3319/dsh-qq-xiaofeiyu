#!/usr/bin/env python3
"""歌词 + 旋律 → 唱歌 wav（DiffSinger / diffsinger_utau）。

给 dsh-qq-bridge 的「唱歌」工具用。约定跟 qq_tts.py 一样：
**歌词从 stdin 读**，音频写到 --out，不经过 shell。

为什么不用 edge-tts：它只会朗读，没有音符级的音高和时长。
这里走 DiffSinger 的完整推理（时长 → 音高 → 方差 → 声学 → 声码器），
旋律来自内置的几段简单曲调（也可以自己传 --notes）。

用法：
    echo "一闪一闪亮晶晶" | python qq_sing.py \
        --voice-bank ~/.dsh/qq-sing/voicebanks/hutao \
        --out /path/to/out.wav --melody 小星星

退出码：
    0  → 写好了
    非 0 → stderr 里是原因
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------- 简谱 / 曲目 ----------
# 用户想唱某首歌时，模型可以：
#   ① 用 --song 选一个曲目（内置 + ~/.dsh/qq-sing/melodies.json 里的自定义）；
#   ② 如果知道这首歌的简谱，用 --notation 直接传（1-7，高音加 '，低音加 ,，长音加 -）。
# 这样就不会所有歌都套同一个调。

音级 = {'1': 'C', '2': 'D', '3': 'E', '4': 'F', '5': 'G', '6': 'A', '7': 'B'}


def 简谱(文本):
    """把简谱字符串解析成 [(音名, 拍数)]。

    支持：
      1-7             中音区（C4-B4）
      0               休止（会被 配旋律 丢掉，不占音节）
      1' / 1^         高八度（可叠加）
      1, / 1_         低八度（可叠加）
      #4 / b7         升降音
      1-              长一拍（1-- 长两拍）
      1.              附点（1.5 拍）
      | ， 、 ;        分隔符，随便用
    """
    from librosa import note_to_midi, midi_to_note
    出 = []
    for raw in re.split(r'[\s|，、;；]+', str(文本 or '').strip()):
        if not raw:
            continue
        tok = raw
        拍 = 1.0
        if tok.endswith('.'):
            拍 = 1.5
            tok = tok[:-1]
        长 = 0
        while tok.endswith('-'):
            长 += 1
            tok = tok[:-1]
        拍 += 长
        高 = len(re.findall(r"['^’]", tok))
        低 = len(re.findall(r'[,,_]', tok))
        tok = re.sub(r"['^’,,_]", '', tok)
        升降 = 0
        if tok[:1] in ('#', '♯'):
            升降 = 1
            tok = tok[1:]
        elif tok[:1] in ('b', '♭'):
            升降 = -1
            tok = tok[1:]
        if tok in ('0', ''):
            出.append(('rest', 拍))
            continue
        if tok in 音级:
            midi = note_to_midi(音级[tok] + str(4 + 高 - 低)) + 升降
            出.append((midi_to_note(midi, unicode=False), 拍))
            continue
        # 已经是音名（外部 melodies.json 里的 "C4:1" 之类）
        if re.fullmatch(r'[A-Ga-g][#b♯♭]?-?\d', tok):
            出.append((tok, 拍))
            continue
        raise SystemExit('看不懂的简谱记号：%s' % raw)
    return 出


# 内置曲目：{bpm, notes: [(音名, 拍数)]}
# 只放确定不会错太多的公共旋律；想加歌就往 ~/.dsh/qq-sing/melodies.json 里加。
# ⚠ 2026-10-31：时值别再全写成 1 拍 —— 用户反馈「没有顿挫，就是文字加音调」。
#   每句结尾拖长、弱起/快字用半拍，听起来才像唱歌而不是念经。
MELODIES = {
    '小星星': {'bpm': 100, 'notes': [
        ('C4', 1), ('C4', 1), ('G4', 1), ('G4', 1), ('A4', 1), ('A4', 1), ('G4', 2),
        ('F4', 1), ('F4', 1), ('E4', 1), ('E4', 1), ('D4', 1), ('D4', 1), ('C4', 2)]},
    '小星星副歌': {'bpm': 100, 'notes': [
        ('F4', 1), ('F4', 1), ('E4', 1), ('E4', 1), ('D4', 1), ('D4', 1), ('C4', 2)]},
    # 两只老虎：完整两段；每句最后一个音拖长
    '两只老虎': {'bpm': 110, 'notes': [
        ('C4', 1), ('D4', 1), ('E4', 1), ('C4', 1),
        ('C4', 1), ('D4', 1), ('E4', 1), ('C4', 1),
        ('E4', 1), ('F4', 1), ('G4', 2),
        ('E4', 1), ('F4', 1), ('G4', 2),
        ('G4', 1), ('A4', 1), ('G4', 1), ('F4', 1), ('E4', 1), ('C4', 2),
        ('G4', 1), ('A4', 1), ('G4', 1), ('F4', 1), ('E4', 1), ('C4', 2),
        ('C4', 1), ('G3', 1), ('C4', 2),
        ('C4', 1), ('G3', 1), ('C4', 2)]},
    # 生日快乐：句尾拖长，开头两字半拍，唱出「祝你」的附点感
    '生日快乐': {'bpm': 110, 'notes': [
        ('G4', 0.5), ('G4', 0.5), ('A4', 1), ('G4', 1), ('C5', 1), ('B4', 2),
        ('G4', 0.5), ('G4', 0.5), ('A4', 1), ('G4', 1), ('D5', 1), ('C5', 2),
        ('G4', 0.5), ('G4', 0.5), ('G4', 1), ('E5', 1), ('C5', 1), ('B4', 2),
        ('F4', 0.5), ('F4', 0.5), ('E4', 1), ('C4', 1), ('D4', 1), ('C4', 2)]},
    # 铃儿响叮当（第一句）；「叮叮当」三连，最后拖长
    '铃儿响叮当': {'bpm': 120, 'notes': [
        ('E4', 1), ('E4', 1), ('E4', 1),
        ('E4', 1), ('E4', 1), ('E4', 1),
        ('E4', 0.5), ('G4', 0.5), ('C4', 1), ('D4', 1), ('E4', 2)]},
    # 找朋友（找呀找呀找朋友 / 找到一个好朋友）
    '找朋友': {'bpm': 110, 'notes': [
        ('G4', 0.5), ('A4', 0.5), ('G4', 1),
        ('E4', 0.5), ('G4', 0.5), ('A4', 0.5), ('G4', 1),
        ('E4', 0.5), ('D4', 0.5), ('E4', 0.5), ('G4', 0.5), ('E4', 1),
        ('D4', 0.5), ('C4', 1.5)]},
    # 没有明显曲调时用的五声音阶，循环起来像随口哼
    '自由': {'bpm': 100, 'notes': [
        ('C4', 1), ('D4', 0.5), ('E4', 0.5), ('G4', 1),
        ('A4', 0.5), ('G4', 0.5), ('E4', 1), ('D4', 1)]},
    # 给「说话音色克隆」造参考音频用的：音高起伏很小、时值短，接近说话而不是唱歌。
    '说话': {'bpm': 150, 'notes': [('A3', 0.55), ('A3', 0.45), ('G3', 0.5), ('A3', 0.5),
                                  ('C4', 0.6), ('A3', 0.45), ('G3', 0.5), ('E3', 0.7)]},
}


def 读曲目文件():
    """读 ~/.dsh/qq-sing/melodies.json（用户自己加的歌），格式：

        {
          "歌名": {"bpm": 110, "notes": "5 6 5 3 5 6 5 3 2 3 5 3 2 1"},
          "另一首": {"notes": ["C4:1", "D4:1", "E4:2"]}
        }

    notes 写成简谱字符串或音名列表都行；同名会覆盖内置曲目。
    """
    路径 = Path.home() / '.dsh' / 'qq-sing' / 'melodies.json'
    if not 路径.exists():
        return {}
    try:
        原 = json.loads(路径.read_text(encoding='utf-8'))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write('melodies.json 读不了（%s），只用内置曲目\n' % e)
        return {}
    出 = {}
    for 名, 值 in (原 or {}).items():
        try:
            if isinstance(值, dict):
                谱 = 值.get('notes') or 值.get('简谱') or 值.get('notation') or ''
                速度 = float(值.get('bpm') or 值.get('速度') or 100)
                歌词 = str(值.get('lyrics') or 值.get('歌词') or '')
            elif isinstance(值, list):
                谱, 速度, 歌词 = 值, 100.0, ''
            elif isinstance(值, str):
                谱, 速度, 歌词 = 值, 100.0, ''
            else:
                continue
            if isinstance(谱, str):
                # 字符串按简谱解析：每个音 = 一个字
                音符 = [[x] for x in 简谱(谱) if x[0] != 'rest']
            else:
                # 列表：每个元素 = 一个字；"F4:1+G4:1" 表示这个字唱两个音
                音符 = []
                for x in 谱:
                    组 = 解析音符组(str(x))
                    if 组:
                        音符.append(组)
            if 音符:
                出[str(名)] = {'bpm': 速度, 'notes': 音符, 'lyrics': 歌词}
        except Exception as e:  # noqa: BLE001
            sys.stderr.write('melodies.json 里「%s」跳过：%s\n' % (名, e))
    return 出


def 全部曲目():
    return {**MELODIES, **读曲目文件()}


def 存曲目(歌名, 谱文, 速度, 歌词):
    """把这支歌的调子记进 melodies.json —— 下次点同一首歌就不用再找谱了。

    2026-11-01：用户点《无敌》时机器人照谱认不全，只能回头要简谱；
    就算它偶尔认对了，下一轮又是白手起家。认对一次就该记住。
    谱文按**原样的简谱字符串**存（不转成音名），这样人和模型都还能改。
    """
    名 = str(歌名 or '').strip()
    谱 = str(谱文 or '').strip()
    if not 名 or not 谱:
        return False, '没有歌名或谱'
    路径 = Path.home() / '.dsh' / 'qq-sing' / 'melodies.json'
    原 = {}
    if 路径.exists():
        try:
            原 = json.loads(路径.read_text(encoding='utf-8')) or {}
        except Exception as e:  # noqa: BLE001
            return False, '原曲目表读不了（%s），这次没存' % e
        try:
            shutil.copy2(str(路径), str(路径) + '.bak')
        except Exception:  # noqa: BLE001
            pass
    原[名] = {
        'notes': 谱,
        'bpm': float(速度 or 100),
        'lyrics': str(歌词 or ''),
        '来源': '照谱转写',
        '存于': time.strftime('%Y-%m-%d %H:%M'),
    }
    try:
        路径.parent.mkdir(parents=True, exist_ok=True)
        路径.write_text(json.dumps(原, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:  # noqa: BLE001
        return False, '曲目表写不进去（%s）' % e
    return True, 名


def 自动匹配曲目(文本):
    """歌词是某首已知歌的副歌时，自动用那首歌的调子。

    2026-10-31 实测：模型被点《爱你》时偷懒选了「自由」，唱出来还是老调子。
    曲目文件里可以写 "lyrics": "如果你突然打了个喷嚏…"，这里按歌词前缀兜底。
    """
    净 = re.sub(r'[^一-鿿]', '', str(文本 or ''))
    if len(净) < 6:
        return None, None
    for 名, 条目 in 全部曲目().items():
        歌 = re.sub(r'[^一-鿿]', '', str(条目.get('lyrics') or ''))
        if not 歌:
            continue
        if 净 in 歌 or 歌 in 净 or 净[:6] == 歌[:6]:
            return 名, 条目
    return None, None

# 跟 diffsinger_utau 的 Phome 用同一套判定（见 package 里的 utils.py）
拼音声母 = set(['b', 'p', 'm', 'f', 'd', 't', 'n', 'l', 'g', 'k', 'h', 'j', 'q', 'x',
              'zh', 'ch', 'sh', 'r', 'z', 'c', 's', 'y', 'w'])
拼音韵母 = set(['ao', 'ei', 'ou', 'an', 'en', 'En', 'in', 'un', 'uan', 'vn', 'van', 'ang',
              'eng', 'ing', 'ong', 'er', 'ia', 'ua', 'ie', 've', 'iao', 'uei', 'iou', 'ian',
              'uen', 'iang', 'uang', 'iong', 'e', 'ui', 'ai', 'uo', 'ir', 'o', 'i0', 'uai',
              'iu', 'v', 'E', 'i', 'a'])


def 读字典():
    """读 opencpop 拼音→音素表（diffsinger_utau 自带）。"""
    try:
        from importlib import resources
        with resources.files('diffsinger_utau').joinpath(
                'dictionaries/opencpop-extension.txt').open('r', encoding='utf-8') as f:
            return 解析字典(f)
    except Exception:
        # 源码目录兜底（直接在 clone 出来的仓库里跑）
        路径 = Path(__file__).resolve().parents[1] / 'diffsinger_utau' / 'dictionaries' / 'opencpop-extension.txt'
        with open(路径, 'r', encoding='utf-8') as f:
            return 解析字典(f)


def 解析字典(fp):
    表 = {'AP': 'AP', 'SP': 'SP'}
    for line in fp:
        if '\t' in line:
            k, v = line.rstrip('\n').split('\t', 1)
            表[k.strip()] = v.strip()
    return 表


def 取音节(文本):
    """中文 → [(汉字, 拼音)]。只取汉字；标点、空白、英文先不支持（会被跳过）。"""
    from pypinyin import pinyin, Style
    音节 = []
    for ch in 文本:
        if not ('一' <= ch <= '鿿'):
            continue
        p = str((pinyin(ch, style=Style.NORMAL) or [['']])[0][0]).strip()
        if not re.fullmatch(r'[a-zA-Z]+', p):
            continue
        音节.append((ch, p))
    return 音节


def 音素序列(音节们, 字典):
    """每个音节 → 音素，前后加 SP。返回 (ph_seq 列表, 拼音串)。"""
    音素 = ['SP']
    拼音串 = ['SP']
    for _ch, p in 音节们:
        拼音串.append(p)
        音素.extend(字典.get(p, p).split())
    音素.append('SP')
    拼音串.append('SP')
    return 音素, ' '.join(拼音串)


def 分词组(音素):
    """复刻 diffsinger_utau 的 Phome：把音素按「词」分组（每组一个音符）。"""
    from itertools import groupby
    序号 = 0
    标 = []
    for i, ph in enumerate(音素):
        标.append(序号)
        if ph in 拼音声母:
            序号 += 1
        elif i + 1 < len(音素) and 音素[i + 1] in ('AP', 'SP'):
            序号 += 1
        elif ph in ('AP', 'SP') and i + 1 < len(音素) and 音素[i + 1] in 拼音韵母:
            序号 += 1
        elif ph in 拼音韵母 and i + 1 < len(音素) and 音素[i + 1] in 拼音韵母:
            序号 += 1
    return [len(list(g)) for _, g in groupby(标)]


def 解析音符组(s):
    """把 "F4:1" / "F4:1+G4:0.5" 解析成 [(音名, 拍数), ...]。

    「+」表示这个字唱多个音（转音）；不带 + 就是普通一个音。
    """
    组 = []
    for part in str(s).split('+'):
        part = part.strip()
        if not part:
            continue
        if ':' in part:
            nt, bt = part.split(':', 1)
            解析 = 简谱(nt.strip())
            if 解析:
                音名, 基础拍 = 解析[0]
                组.append((音名, 基础拍 * float(bt)))
        else:
            组.extend(简谱(part))
    return [(n, b) for n, b in 组 if n != 'rest']


def 配旋律(音节数, 名字, 自定义, 简谱文本):
    """选旋律：简谱 > 自定义音名 > 曲目名。

    返回 (名字, [[(音名, 拍数), ...], ...], 曲目bpm)。
    外层一个元素 = 一个音节；内层多个音 = 这个字唱多个音（转音/一字多音）。
    音符比音节多就截，少就循环；休止符丢掉（它不占音节）。
    """
    曲目 = 全部曲目()
    曲bpm = None
    if 简谱文本:
        原 = 简谱(简谱文本)
        音符 = [[x] for x in 原 if x[0] != 'rest']
        名字 = '简谱'
    elif 自定义:
        原 = 自定义.replace(',', ' ').split()
        音符 = [[(x, 1.0)] for x in 原 if x]
        名字 = '自定义'
    else:
        条目 = 曲目.get(名字)
        if not 条目:
            raise SystemExit('不认识的旋律：%s（可用：%s）' % (名字, '、'.join(sorted(曲目))))
        原 = list(条目['notes'])
        # 内置曲目是 (音名, 拍数) 的平铺列表；自定义曲目可能是「一个字多个音」的分组列表
        音符 = []
        for x in 原:
            if isinstance(x, list):
                组 = [(n, b) for n, b in x if n != 'rest']
                if 组:
                    音符.append(组)
            elif isinstance(x, tuple):
                if x[0] != 'rest':
                    音符.append([x])
            else:
                # 兼容 "F4:1" / "F4:1+G4:1" 字符串
                组 = 解析音符组(str(x))
                if 组:
                    音符.append(组)
        曲bpm = 条目.get('bpm')
    音符 = [g for g in 音符 if g]
    if not 音符:
        raise SystemExit('旋律里没有可唱的音符')
    if len(音符) >= 音节数:
        配 = 音符[:音节数]
    else:
        配 = [音符[i % len(音符)] for i in range(音节数)]
    return 名字, 配, 曲bpm


def 生成_ds(文本, 旋律名, 自定义音符, 简谱文本, bpm, 字典):
    音节们 = 取音节(文本)
    if not 音节们:
        raise SystemExit('歌词里没有可唱的中文字')
    音素, 拼音串 = 音素序列(音节们, 字典)
    分组 = 分词组(音素)
    # 正常情况下「音节数 + 2」；万一有音节的切分和拼音表不一致，以实际分组为准
    音符数 = len(分组) - 2
    if 音符数 <= 0:
        raise SystemExit('音素分组不对：%s' % 分组)
    # 模型偷懒选了「自由/默认小星星」时，按歌词自动认歌
    if not 简谱文本 and not 自定义音符 and 旋律名 in ('', '自由', '小星星'):
        自动名, 自动条目 = 自动匹配曲目(文本)
        if 自动条目:
            旋律名 = 自动名
    名字, 配, 曲bpm = 配旋律(音符数, 旋律名, 自定义音符, 简谱文本)
    if len(配) != 音符数:
        raise SystemExit('音素分组数 %d 和音符数 %d 对不上' % (len(分组), len(配) + 2))
    实际bpm = float(bpm or 曲bpm or 100)
    一拍 = 60.0 / 实际bpm
    音符名 = ['rest']
    时长 = [0.35]
    滑 = ['0']
    for 组 in 配:
        for j, (n, b) in enumerate(组):
            音符名.append(n)
            时长.append(b * 一拍)
            滑.append('1' if j > 0 else '0')
    音符名.append('rest')
    时长.append(0.45)
    滑.append('0')
    return {
        'offset': 0.0,
        'text': 拼音串,
        'ph_seq': ' '.join(音素),
        'ph_num': ' '.join(str(x) for x in 分组),
        'note_seq': ' '.join(音符名),
        'note_dur': ' '.join('%.4f' % x for x in 时长),
        'note_slur': ' '.join(滑),
        'input_type': 'phoneme',
    }, 名字, 实际bpm


def 校正音高(路径, ds, 阈值=50, 淡=0.02):
    """把明显跑调的音拉回目标音高（只动偏差 > 阈值的音）。

    2026-10-31 用户反馈「有些地方跑调」：DiffSinger 在短音/音程跳进时会欠冲，
    例如 F4→D4 的快音只唱到 -40 音分。这里按 note_dur 定位每个音，取中间段
    的 F0 中位数；偏了就写一张 rubberband 的 pitch map，整轨一次处理
    （比分段 pitch_shift 少接缝，带 -F 保共振峰）。不跑调的音一律不动。
    """
    import librosa
    import numpy as np
    import shutil
    音源 = 路径 + '.tune-in.wav'
    try:
        shutil.copyfile(路径, 音源)
        y, sr = librosa.load(音源, sr=None, mono=True)
        notes = str(ds.get('note_seq') or '').split()
        durs = [float(x) for x in str(ds.get('note_dur') or '').split()]
        if not notes or not durs or len(notes) != len(durs):
            return
        总 = sum(durs)
        if 总 <= 0:
            return
        倍 = (len(y) / sr) / 总
        f0, _, _ = librosa.pyin(y, fmin=75, fmax=600, sr=sr, frame_length=2048, hop_length=256)
        times = np.arange(len(f0)) * 256 / sr
        行 = [(0, 0.0)]
        改了 = 0
        t = 0.0
        for note, d in zip(notes, durs):
            a, b = t, t + d * 倍
            c = 0.0
            if note != 'rest' and (b - a) > 0.08:
                sel = (times >= a + 0.2 * (b - a)) & (times <= b - 0.2 * (b - a)) & (~np.isnan(f0))
                if sel.sum() >= 3:
                    med = float(np.median(f0[sel]))
                    if med > 0:
                        tgt = float(librosa.midi_to_hz(librosa.note_to_midi(note)))
                        dev = 1200.0 * math.log2(med / tgt)
                        if abs(dev) > 阈值:
                            c = max(-1.0, min(1.0, -dev / 100.0))
                            改了 += 1
            行.append((int(a * sr), c))
            行.append((max(int(a * sr), int(b * sr) - 1), c))
            t = b
        行.append((max(0, len(y) - 1), 0.0))
        if not 改了:
            print('校音：没有明显跑调的音', file=sys.stderr)
            return
        rb = shutil.which('rubberband')
        if not rb:
            print('校音：没装 rubberband，跳过（apt/pacman 装 rubberband）', file=sys.stderr)
            return
        图 = 路径 + '.pitchmap.txt'
        with open(图, 'w', encoding='utf-8') as f:
            for fr, c in 行:
                f.write('%d %.4f\n' % (fr, c))
        r = subprocess.run([rb, '-3', '-F', '--pitchmap', 图, '-t1', 音源, 路径],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print('校音：rubberband 失败（%s）' % (r.stderr or '').strip()[:200], file=sys.stderr)
        else:
            print('校音：调整了 %d 个音（阈值 %d 音分）' % (改了, 阈值), file=sys.stderr)
        try:
            os.unlink(图)
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001
        print('校音出错（保持原音频）：%s' % e, file=sys.stderr)
    finally:
        try:
            os.unlink(音源)
        except Exception:
            pass


def 合成(ds_dict, voice_bank, out, speaker, key_shift, steps_acoustic, steps_pitch, steps_var):
    from diffsinger_utau.voice_bank.pred_all import PredAll
    from diffsinger_utau.voice_bank.commons.ds_reader import DSReader
    pk = Path(voice_bank)
    if not pk.exists():
        raise SystemExit('声库目录不存在：%s' % pk)
    ds = DSReader.DSSection(dict(ds_dict))
    工作 = Path(tempfile.mkdtemp(prefix='qq-sing-'))
    try:
        print('加载声库：%s' % pk, file=sys.stderr)
        预测 = PredAll(pk)
        结果 = 预测.predict_full_pipeline(
            ds=ds, lang='zh', speaker=speaker, key_shift=key_shift,
            pitch_steps=steps_pitch, variance_steps=steps_var,
            acoustic_steps=steps_acoustic, gender=0.0,
            output_dir=str(工作), save_intermediate=False,
        )
        src = Path(结果['audio_path'])
        if not src.exists() or src.stat().st_size == 0:
            raise SystemExit('推理没产出音频')
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
    finally:
        shutil.rmtree(工作, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--voice-bank', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--song', '--melody', dest='song', default='小星星',
                    help='曲目名（内置 / melodies.json）')
    ap.add_argument('--notation', default='', help='简谱，例如 "1 1 5 5 6 6 5"；给了就优先用它')
    ap.add_argument('--notes', default='', help='自定义音名，空格分隔，例如 "C4 D4 E4 G4"')
    ap.add_argument('--bpm', type=float, default=0,
                    help='速度；0 = 用曲目自带的速度（没有就 100）')
    ap.add_argument('--speaker', default=None)
    ap.add_argument('--key-shift', type=int, default=0)
    ap.add_argument('--acoustic-steps', type=int, default=20)
    ap.add_argument('--pitch-steps', type=int, default=10)
    ap.add_argument('--variance-steps', type=int, default=10)
    ap.add_argument('--save-song', action='store_true',
                    help='把这次用的简谱记进 melodies.json（下次点同一首歌直接唱）')
    ap.add_argument('--tune', action='store_true',
                    help='尝试自动校音（实验；默认关 —— 实测会把「一定」咬成「一点」，伤咬字）')
    ap.add_argument('--tune-threshold', type=int, default=50, help='偏差超过多少音分才拉回，默认 50')
    a = ap.parse_args()

    文本 = ' '.join(sys.stdin.read().split()).strip()
    if not 文本:
        sys.stderr.write('没有从 stdin 读到歌词\n')
        return 2
    if len(文本) > 60:
        文本 = 文本[:60]
        sys.stderr.write('歌词过长，截到 60 字\n')

    字典 = 读字典()
    ds, 名字, 实际bpm = 生成_ds(文本, a.song, a.notes, a.notation, a.bpm, 字典)
    print('旋律：%s（BPM %s），歌词：%s' % (名字, 实际bpm, 文本), file=sys.stderr)
    if a.save_song:
        谱文 = a.notation or a.notes
        if 谱文:
            好了, 说明 = 存曲目(a.song, 谱文, a.bpm or 实际bpm, 文本)
            print(('记住了《%s》的调子' if 好了 else '没记住：%s') % 说明, file=sys.stderr)
        else:
            print('没给简谱，不用记', file=sys.stderr)
    合成(ds, a.voice_bank, a.out, a.speaker, a.key_shift,
         a.acoustic_steps, a.pitch_steps, a.variance_steps)
    if a.tune:
        校正音高(a.out, ds, a.tune_threshold)
    print('OK %s' % a.out, file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
