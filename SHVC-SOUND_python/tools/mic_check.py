"""
マイクが実機(SHVC-SOUND)の音を拾えているかを、合図音で確かめる。

440/1000/2000Hz の純音を 0.5秒ずつ、0.5秒の無音をはさんで並べた音声を作り、
pcm_clip_test.py で実機に鳴らしながら録音する。録音から各周波数の強さを時間ごとに調べ、
鳴らした時刻にだけその周波数が出ていれば「聞こえている」と判定する。

使い方(tools/.venv-transcribe の python で実行):
  python mic_check.py [--device 1] [--port COM10]
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
MIC_RATE = 44100
TONES = [440, 1000, 2000]


def make_signal(path, rate=16000, rounds=2):
    seg = int(0.5 * rate)
    t = np.arange(seg) / rate
    fade = np.minimum(1, np.minimum(np.arange(seg), np.arange(seg)[::-1]) / (0.01 * rate))
    parts, schedule, clock = [], [], 0.0
    for _ in range(rounds):
        for f in TONES:
            parts.append(0.9 * np.sin(2 * np.pi * f * t) * fade)
            schedule.append((clock, f))
            parts.append(np.zeros(seg))
            clock += 1.0
    sf.write(path, np.concatenate(parts).astype(np.float32), rate)
    return schedule, clock


def tone_power(y, sr, f):
    n = len(y)
    k = np.arange(n)
    ref = np.exp(-2j * np.pi * f * k / sr)
    return float(np.abs(np.dot(y * np.hanning(n), ref)) / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="1")
    ap.add_argument("--port", default="COM10")
    args = ap.parse_args()
    dev = int(args.device) if args.device.isdigit() else args.device

    sig = os.path.join(HERE, "mic_check_signal.wav")
    schedule, length = make_signal(sig)
    chunks = []
    t0 = time.time()
    # 再生の準備(リセット・転送)にかかる時間は読めないので、再生処理が終わるまで録り続ける
    with sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="float32", device=dev,
                        callback=lambda data, frames, t, status: chunks.append(data[:, 0].copy())):
        subprocess.call([sys.executable, os.path.join(HERE, "pcm_stream.py"), sig, "--rate", "16000",
                         "--filter0", "--peak", "0.85", "--loop-whole", "--static-loop", f"{length:.1f}",
                         "--volume", "127", "--port", args.port],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
    y = np.concatenate(chunks)
    sf.write(os.path.join(HERE, "mic_check_recording.wav"), y, MIC_RATE)
    print(f"録音 {len(y) / MIC_RATE:.1f}秒(再生処理 {time.time() - t0:.1f}秒)")

    # 転送時間のぶん再生開始がずれるので、最初の合図音(440Hz)が一番強く出る位置を探して合わせる
    win = int(0.4 * MIC_RATE)
    step = int(0.05 * MIC_RATE)
    p440 = [tone_power(y[i:i + win], MIC_RATE, 440) for i in range(0, len(y) - win, step)]
    noise = np.median(p440)
    start = None
    last_start = len(y) / MIC_RATE - length
    for i, p in enumerate(p440):
        if p > noise * 8 and i * step / MIC_RATE <= last_start:
            start = i * step / MIC_RATE
            break
    if start is None:
        print("合図音が見つかりません。マイクがスピーカーの音を拾えていないか、音が小さすぎます")
        print(f"(440Hzの強さ 最大{max(p440):.2e} / 中央値{noise:.2e})")
        return 1

    print(f"最初の合図音を録音の {start:.2f}秒 に検出")
    ok = 0
    for t, f in schedule:
        a = int((start + t + 0.05) * MIC_RATE)
        on = y[a:a + win]
        off = y[a + int(0.5 * MIC_RATE):a + int(0.5 * MIC_RATE) + win]
        p_on, p_off = tone_power(on, MIC_RATE, f), tone_power(off, MIC_RATE, f)
        ratio = 20 * np.log10((p_on + 1e-12) / (p_off + 1e-12))
        hit = ratio > 10
        ok += hit
        print(f"  {t:4.1f}秒 {f:5d}Hz: 鳴っている間と無音の差 {ratio:5.1f}dB {'○' if hit else '×'}")
    print(f"判定: {ok}/{len(schedule)} 個の合図音を検出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
