"""
マイクで実機の音を録音し、音量の推移・無音区間・周波数の傾向を数値で出す(遠隔での確認用)。

使い方(tools/.venv-transcribe の python で実行):
  python listen.py 秒数 [--out 録音.wav] [--device 1] [--ref 元の音声.wav --ref-start 0]
  --ref を付けると、録音と元の音声のずれ(相互相関)と、帯域ごとの音量差も出す
"""
import argparse

import numpy as np
import sounddevice as sd
import soundfile as sf

RATE = 44100


def db(x):
    return 20 * np.log10(max(float(x), 1e-9))


def band_levels(y, sr):
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1 / sr)
    bands = [(60, 250), (250, 1000), (1000, 3000), (3000, 6000), (6000, 12000)]
    return {f"{lo}-{hi}Hz": db(np.sqrt(np.mean(spec[(freqs >= lo) & (freqs < hi)] ** 2)) + 1e-12)
            for lo, hi in bands}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("seconds", type=float)
    ap.add_argument("--out", default="listen.wav")
    ap.add_argument("--device", default=None)
    ap.add_argument("--ref", default=None)
    ap.add_argument("--ref-start", type=float, default=0.0)
    args = ap.parse_args()

    dev = int(args.device) if args.device and args.device.isdigit() else args.device
    y = sd.rec(int(args.seconds * RATE), samplerate=RATE, channels=1, dtype="float32", device=dev)
    sd.wait()
    y = y[:, 0]
    sf.write(args.out, y, RATE)

    win = int(0.5 * RATE)
    levels = [db(np.sqrt(np.mean(y[i:i + win] ** 2))) for i in range(0, len(y) - win + 1, win)]
    floor = np.percentile(levels, 10)
    print(f"録音 {args.seconds:g}秒 -> {args.out}")
    print("0.5秒ごとの音量(dBFS): " + " ".join(f"{v:.0f}" for v in levels))
    quiet = [i * 0.5 for i, v in enumerate(levels) if v < floor + 3]
    print(f"全体 {db(np.sqrt(np.mean(y ** 2))):.1f}dBFS / 最小付近 {floor:.1f}dBFS / ピーク {db(np.max(np.abs(y))):.1f}dBFS")
    print("帯域ごとの強さ(相対dB): " + " ".join(f"{k}:{v:.0f}" for k, v in band_levels(y, RATE).items()))
    if len(quiet) > len(levels) * 0.5:
        print("※ 半分以上の区間が最小付近の音量です(ほぼ無音か、一定の小さな音)")

    if args.ref:
        import librosa
        ref, _ = librosa.load(args.ref, sr=RATE, mono=True, offset=args.ref_start,
                              duration=args.seconds + 10)
        n = min(len(y), len(ref))
        a = (y[:n] - y[:n].mean()) / (y[:n].std() + 1e-9)
        b = (ref[:n] - ref[:n].mean()) / (ref[:n].std() + 1e-9)
        # 音量の包絡同士で相関をとる(マイクと部屋の響きで波形そのものは一致しないため)
        hop = 441
        ea = np.sqrt(np.convolve(a ** 2, np.ones(hop) / hop, "same"))[::hop]
        eb = np.sqrt(np.convolve(b ** 2, np.ones(hop) / hop, "same"))[::hop]
        ea, eb = ea - ea.mean(), eb - eb.mean()
        corr = np.correlate(ea, eb, "full")
        lag = (np.argmax(corr) - (len(eb) - 1)) * hop / RATE
        score = corr.max() / (np.linalg.norm(ea) * np.linalg.norm(eb) + 1e-9)
        print(f"元の音声との一致度(音量の包絡の相関) {score:.2f} / ずれ {lag:+.2f}秒")


if __name__ == "__main__":
    main()
