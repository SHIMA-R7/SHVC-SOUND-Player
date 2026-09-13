"""
案A(録音をそのままS-DSPで鳴らす)の実現性確認。

録音の一部を指定のサンプルレートにしてBRRに変換し、ARAMに丸ごと載せて
1ボイスで最後まで鳴らす。ストリーミングはまだしない(ARAMに入る数秒だけ)。

  ARAM上のBRR領域は $0400-$FFBF の約63.9KB。BRRは16サンプルで9バイトなので
    16000Hz なら約7.1秒 / 11025Hz なら約10.3秒 が上限。

使い方(tools/.venv-transcribe の python で実行):
  python pcm_clip_test.py 入力.wav --start 20 --rate 16000 [--seconds 7] [--port COM10] [--wav-out 確認用.wav]
"""
import argparse
import os
import sys
import time

import librosa
import numpy as np
import soundfile as sf

PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # SHVC-SOUND_python
sys.path.insert(0, PY_DIR)
from midi2spc import brr, engine, hardware  # noqa: E402

BRR_MAX_BYTES = 0xFFC0 - hardware.SAMPLE_ADDR


class Clip:
    """HardwarePlayer.upload が音色として扱えるだけの最小限の入れ物。"""

    def __init__(self, brr_data):
        self.brr_data = brr_data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--start", type=float, default=0.0, help="切り出し開始位置(秒)")
    ap.add_argument("--seconds", type=float, default=None, help="長さ(省略時はARAMに入るだけ)")
    ap.add_argument("--rate", type=int, default=16000, help="BRRのサンプルレート")
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--volume", type=int, default=100, help="VOLL/VOLR (0-127)")
    ap.add_argument("--wav-out", default=None, help="BRRを復号した音をWAVに書く(PCで確認用)")
    ap.add_argument("--no-play", action="store_true")
    args = ap.parse_args()

    max_seconds = (BRR_MAX_BYTES // brr.BLOCK_BYTES) * brr.BLOCK_SAMPLES / args.rate
    seconds = min(args.seconds or max_seconds, max_seconds)
    y, _ = librosa.load(args.wav, sr=args.rate, mono=True, offset=args.start, duration=seconds)
    max_samples = (BRR_MAX_BYTES // brr.BLOCK_BYTES) * brr.BLOCK_SAMPLES
    y = y[:min(len(y), int(seconds * args.rate), max_samples)]
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.95
    print(f"{args.rate}Hz / {len(y) / args.rate:.2f}秒 ({len(y)}サンプル) をBRRに変換中...", flush=True)

    t = time.time()
    data = brr.encode(y, loop=False)
    print(f"  BRR {len(data)}バイト ({len(data) / 1024:.1f}KB, 上限{BRR_MAX_BYTES / 1024:.1f}KB) "
          f"{time.time() - t:.1f}秒", flush=True)

    if args.wav_out:
        pcm, _ = brr.decode(data)
        sf.write(args.wav_out, np.asarray(pcm, dtype=np.float32), args.rate)
        print(f"  復号した音: {args.wav_out}")

    if args.no_play:
        return 0

    pitch = int(round(engine.PITCH_UNITY * args.rate / 32000))
    duration = len(y) / args.rate
    # ADSR有効・立ち上がり即時・サステイン最大・減衰なし = 一定の音量で鳴らし続ける
    events = [
        engine.KeyOn(0.2, 0, "clip", pitch, args.volume, args.volume, 0x8F, 0xE0),
        engine.KeyOff(0.2 + duration + 0.1, 0),
    ]
    print(f"実機で再生 (PITCH=${pitch:04X})", flush=True)
    hardware.play_on_hardware(args.port, events, {"clip": Clip(data)})
    print("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
