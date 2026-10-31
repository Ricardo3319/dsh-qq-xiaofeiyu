#!/usr/bin/env python3
"""把一段 WAV 转成文字（SenseVoice / sherpa-onnx 版，离线、免费）。

给 dsh-qq-bridge 的「语音转写」用的：插件只负责把 QQ 语音条交给你指定的命令，
这个脚本是**其中一种**接法（本机 SenseVoice）。你本机没有这套环境也没关系 ——
用你自己的 whisper / 云端 API 写一条同样「读 {file}、往 stdout 打文字」的命令就行。

用法：
    语音转写命令 里填：
    "<你的 python.exe>" "<这个脚本的绝对路径>" "{file}"

要准备的东西（三样，缺一不可）：
    pip install sherpa-onnx numpy soundfile
    模型：SenseVoice int8（model.int8.onnx + tokens.txt），放到 --模型目录 里，或者用环境变量 ASR_MODEL_DIR

退出码 / 输出约定：
    成功 → stdout 打印一行文字（插件把它当成转写结果）
    失败 → 非 0 退出码，错误写到 stderr（插件会显示「转写失败：…」）
"""
import argparse
import os
import sys
import wave


def 读_wav(路径: str):
    with wave.open(路径, "rb") as w:
        声道 = w.getnchannels()
        位宽 = w.getsampwidth()
        采样率 = w.getframerate()
        帧数 = w.getnframes()
        数据 = w.readframes(帧数)
    if 位宽 != 2:
        raise SystemExit("只吃 16-bit PCM 的 wav（这条是 %d bit）—— 先用 ffmpeg 转一下" % (位宽 * 8))
    import numpy as np
    音频 = np.frombuffer(数据, dtype=np.int16).astype("float32") / 32768.0
    if 声道 > 1:
        音频 = 音频.reshape(-1, 声道).mean(axis=1)
    if 采样率 != 16000:
        n = int(len(音频) * 16000 / 采样率)
        x = np.linspace(0.0, len(音频) - 1, n)
        音频 = np.interp(x, np.arange(len(音频)), 音频).astype("float32")
    return 音频


def 找模型(目录: str):
    m = os.path.join(目录, "model.int8.onnx")
    t = os.path.join(目录, "tokens.txt")
    if not (os.path.exists(m) and os.path.exists(t)):
        raise SystemExit("模型目录里缺 model.int8.onnx / tokens.txt：%s" % 目录)
    return m, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="要转写的 wav 路径")
    ap.add_argument("--模型目录", default=os.environ.get("ASR_MODEL_DIR", ""))
    ap.add_argument("--线程", type=int, default=4)
    a = ap.parse_args()

    if not os.path.exists(a.file):
        raise SystemExit("找不到音频文件：%s" % a.file)
    if not a.模型目录:
        raise SystemExit("没给模型目录（--模型目录 或 环境变量 ASR_MODEL_DIR）")

    model, tokens = 找模型(a.模型目录)
    import sherpa_onnx

    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=model, tokens=tokens, num_threads=a.线程, use_itn=True,
    )
    音频 = 读_wav(a.file)
    s = rec.create_stream()
    s.accept_waveform(16000, 音频)
    rec.decode_stream(s)
    文本 = (s.result.text or "").strip()
    sys.stdout.write(文本)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
