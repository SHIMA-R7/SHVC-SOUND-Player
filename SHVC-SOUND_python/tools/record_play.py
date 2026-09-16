"""
再生コマンドを実行している間ずっとマイクで録音し、途切れ(急な無音)と元の音声との一致度を調べる。

使い方(tools/.venv-transcribe の python で実行):
  python record_play.py --out 録音.wav [--ref 元の音声.wav] [--device 1] -- 再生コマンド...
例:
  python record_play.py --out rec.wav --ref song.wav -- python pcm_stream.py song.wav --rate 22050 --seconds 60
"""
import argparse
import subprocess
import sys
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

RATE = 44100


def main():
    if "--" not in sys.argv:
        print(__doc__)
        return 1
    split = sys.argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", default=None)
    ap.add_argument("--ref-start", type=float, default=0.0)
    ap.add_argument("--device", default="1")
    args = ap.parse_args(sys.argv[1:split])
    cmd = sys.argv[split + 1:]
    dev = int(args.device) if args.device.isdigit() else args.device

    chunks = []
    t0 = time.time()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", device=dev,
                        callback=lambda d, f, t, s: chunks.append(d[:, 0].copy())):
        rc = subprocess.call(cmd)
        time.sleep(1.0)
    y = np.concatenate(chunks)
    sf.write(args.out, y, RATE)
    print(f"[録音] {len(y) / RATE:.1f}秒 -> {args.out} (再生コマンドの終了コード {rc}, {time.time() - t0:.0f}秒)")

    win = int(0.1 * RATE)
    lv = np.array([20 * np.log10(np.sqrt(np.mean(y[i:i + win] ** 2)) + 1e-9)
                   for i in range(0, len(y) - win + 1, win)])
    floor = np.percentile(lv, 5)
    active = lv > floor + 12
    if active.any():
        first, last = np.argmax(active), len(active) - 1 - np.argmax(active[::-1])
        body = lv[first:last + 1]
        # 鳴っている区間の途中で、前後より急に20dB以上落ちた0.1秒を「途切れ候補」とする
        drops = [first + i for i in range(1, len(body) - 1)
                 if body[i] < min(body[i - 1], body[i + 1]) - 20]
        print(f"[録音] 音が出ていた区間 {first * 0.1:.1f}〜{last * 0.1:.1f}秒 / 平均 {body.mean():.1f}dBFS / "
              f"無音時 {floor:.1f}dBFS / 途切れ候補 {len(drops)}か所"
              + (": " + " ".join(f"{d * 0.1:.1f}秒" for d in drops[:10]) if drops else ""))
    else:
        print("[録音] 無音時とほぼ変わらない音量でした(音が出ていない可能性)")
        return rc

    if args.ref:
        import librosa
        ref, _ = librosa.load(args.ref, sr=RATE, mono=True, offset=args.ref_start)
        hop = 441
        env = lambda x: np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, "same"))[::hop]
        ea = env(y[first * win:(last + 1) * win])
        eb = env(ref[:len(ea) * hop + RATE * 5])
        ea, eb = np.log(ea + 1e-4), np.log(eb + 1e-4)
        ea, eb = ea - ea.mean(), eb - eb.mean()
        best = (-1, 0)
        for lag in range(0, max(1, len(eb) - len(ea)), 5):
            seg = eb[lag:lag + len(ea)]
            if len(seg) < len(ea):
                break
            c = float(np.dot(ea, seg) / (np.linalg.norm(ea) * np.linalg.norm(seg) + 1e-9))
            if c > best[0]:
                best = (c, lag)
        print(f"[録音] 元の音声との一致度(音量の起伏の相関) {best[0]:.2f} (1に近いほど同じ曲の同じ部分)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
