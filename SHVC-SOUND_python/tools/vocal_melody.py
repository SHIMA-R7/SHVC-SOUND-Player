"""
分離したボーカル音声から、主旋律だけを単音のノート列として取り出す。

Basic Pitchは楽器向けで、歌のビブラートやしゃくり・母音の倍音で
音程がブレたり細切れになりやすい。こちらは単音専用の基本周波数推定(pYIN)で
フレームごとの音程を取り、平滑化してから半音に丸めてノートにまとめる。

使い方(tools/.venv-transcribe の python で実行):
  python vocal_melody.py vocals.wav 出力.mid [--program 81] [--min-ms 110]
  入力はチューニング補正済みのもの(separate_transcribe.py の *_tuned.wav)を想定
"""
import argparse

import librosa
import numpy as np
import pretty_midi
import scipy.ndimage


def extract_notes(path, min_ms=110, max_gap_ms=60):
    y, sr = librosa.load(path, sr=22050, mono=True)
    hop = 256
    f0, voiced, prob = librosa.pyin(y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C6"),
                                    sr=sr, frame_length=2048, hop_length=hop)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0][: len(f0)]
    midi = librosa.hz_to_midi(np.where(voiced, f0, np.nan))
    # ビブラートやしゃくりを均してから半音に丸める(約70msの中央値)
    filled = np.where(np.isnan(midi), 0.0, midi)
    smooth = scipy.ndimage.median_filter(filled, size=11)
    pitch = np.where(np.isnan(midi), -1, np.round(smooth)).astype(int)

    frame_s = hop / sr
    notes = []
    start = None
    for i in range(len(pitch) + 1):
        p = pitch[i] if i < len(pitch) else -1
        if start is not None and p != pitch[start]:
            notes.append([start * frame_s, i * frame_s, int(pitch[start]),
                          float(np.mean(rms[start:i]))])
            start = None
        if start is None and p > 0:
            start = i

    # 短すぎる音は、直前の同じ高さの音とつなぐか捨てる
    merged = []
    for n in notes:
        if merged and n[2] == merged[-1][2] and n[0] - merged[-1][1] <= max_gap_ms / 1000:
            merged[-1][1] = n[1]
            continue
        merged.append(n)
    out = [n for n in merged if (n[1] - n[0]) * 1000 >= min_ms]
    peak = max((n[3] for n in out), default=1.0) or 1.0
    return [(s, e, p, a / peak) for s, e, p, a in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("out_mid")
    ap.add_argument("--program", type=int, default=81)
    ap.add_argument("--min-ms", type=int, default=110)
    args = ap.parse_args()

    notes = extract_notes(args.wav, min_ms=args.min_ms)
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=args.program, name="vocals")
    for s, e, p, a in notes:
        inst.notes.append(pretty_midi.Note(velocity=int(np.clip(50 + a * 77, 50, 127)),
                                           pitch=p, start=s, end=e))
    pm.instruments.append(inst)
    pm.write(args.out_mid)
    ps = [n[2] for n in notes]
    print(f"メロディ {len(notes)}音 音域{min(ps)}-{max(ps)} -> {args.out_mid}")


if __name__ == "__main__":
    main()
