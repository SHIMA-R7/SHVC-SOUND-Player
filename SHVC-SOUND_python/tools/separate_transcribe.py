"""
歌とバンドが混ざった音源を、SHVC-SOUND(8ボイス)向けのMIDIにする。

  1. Demucs(htdemucs)で vocals / bass / drums / other に分離
  2. vocals と bass は Basic Pitch で採譜し、同時に1音だけ残す(単旋律化)
  3. other は感度を低めにして和音の骨組みだけ拾い、同時発音数を制限する
  4. パートごとに音色を割り当てて1つのMIDIに書き出す
     ch1 = ボーカル(主旋律), ch2 = ベース, ch3 = 伴奏  ※ドラムは採譜しない

使い方(tools/.venv-transcribe の python で実行):
  python separate_transcribe.py 入力.wav 出力.mid [--stems 分離音の保存先]
"""
import argparse
import os
import time

import numpy as np
import pretty_midi
import soundfile as sf
import torch
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict
from demucs.apply import apply_model
from demucs.audio import convert_audio
from demucs.pretrained import get_model

# パートごとの設定: (GM音色, onset閾値, frame閾値, 最短ノートms, 同時発音数上限, 残し方)
PARTS = {
    "vocals": (81, 0.5, 0.3, 90, 1, "loudest"),   # sawlead
    "bass":   (38, 0.5, 0.3, 90, 1, "lowest"),    # synbass
    "other":  (0,  0.6, 0.4, 120, 3, "loudest"),  # piano
}


def separate(wav_path, stems_dir):
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    model = get_model("htdemucs")
    model.eval()
    wav = torch.from_numpy(audio.T.copy())
    # モデルは44.1kHzステレオ前提。YouTube等の48kHzやモノラルはここで合わせる
    wav = convert_audio(wav, sr, model.samplerate, model.audio_channels)
    sr = model.samplerate
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        sources = apply_model(model, wav[None], device="cpu", split=True, overlap=0.25, progress=True)[0]
    sources = sources * (ref.std() + 1e-8) + ref.mean()
    os.makedirs(stems_dir, exist_ok=True)
    paths = {}
    for name, src in zip(model.sources, sources):
        p = os.path.join(stems_dir, f"{name}.wav")
        sf.write(p, src.numpy().T, sr)
        paths[name] = p
    return paths


def limit_polyphony(notes, max_voices, keep):
    """notes: (start, end, pitch, amp) のリスト。同時に鳴る数を max_voices 以下にする。"""
    kept = []
    for s, e, p, a in sorted(notes, key=lambda n: n[0]):
        new = [s, e, p, a]
        active = [k for k in kept if k[1] > s]
        if len(active) < max_voices:
            kept.append(new)
            continue
        # あふれたら、残す基準で一番弱いもの(lowest=一番高い音 / loudest=一番小さい音)を外す
        rank = (lambda k: k[2]) if keep == "lowest" else (lambda k: -k[3])
        victim = max(active + [new], key=rank)
        if victim is new:
            continue                      # 新しい音のほうが弱いので捨てる
        victim[1] = s                     # 鳴っていた音を新しい音の頭で切る
        kept.append(new)
    return [k for k in kept if k[1] - k[0] > 0.03]


def detune_stems(paths, stems_dir, cents=None):
    """
    音源全体のチューニングのずれを測り、分離音をA=440Hzに合わせ直す。

    動画サイトの転載には、検出逃れで数十セントずらしたものがある。
    半音の真ん中(±50セント付近)にずれていると、Basic Pitchの丸めで
    同じ音が隣の半音と行ったり来たりし、キーが崩壊する。
    """
    import librosa
    if cents is None:
        ests = []
        for name in ("vocals", "other", "bass"):
            y, sr = librosa.load(paths[name], sr=22050, mono=True, duration=120)
            ests.append(librosa.estimate_tuning(y=y, sr=sr))
        cents = float(np.median(ests)) * 100
    print(f"  チューニングのずれ {cents:+.0f}セント -> 補正して採譜します", flush=True)
    if abs(cents) < 10:
        return paths
    tuned = {}
    for name in ("vocals", "bass", "other"):
        y, sr = librosa.load(paths[name], sr=22050, mono=True)
        y = librosa.effects.pitch_shift(y, sr=sr, n_steps=-cents / 100)
        p = os.path.join(stems_dir, f"{name}_tuned.wav")
        sf.write(p, y, sr)
        tuned[name] = p
    return tuned


def fix_octaves(notes, window=9, limit=9):
    """
    単旋律パートの1オクターブずれ(倍音を拾った誤検出)を直す。
    前後の音の中央値から limit 半音以上離れた音を、オクターブ単位で寄せる。
    """
    pitches = [n[2] for n in notes]
    fixed = []
    for i, n in enumerate(notes):
        lo, hi = max(0, i - window // 2), min(len(notes), i + window // 2 + 1)
        med = float(np.median(pitches[lo:hi]))
        p = n[2]
        while p - med >= limit:
            p -= 12
        while med - p >= limit:
            p += 12
        fixed.append([n[0], n[1], p, n[3]])
    return fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("out_mid")
    ap.add_argument("--stems", default=None)
    ap.add_argument("--reuse-stems", action="store_true",
                    help="分離済みの音声があれば分離を飛ばして採譜だけやり直す")
    ap.add_argument("--vocals", default=None, metavar="ONSET,FRAME",
                    help="ボーカルの採譜閾値(例: 0.4,0.25)")
    ap.add_argument("--other", default=None, metavar="ONSET,FRAME",
                    help="伴奏の採譜閾値(例: 0.4,0.25)")
    ap.add_argument("--tune-cents", default="auto",
                    help="チューニング補正。auto=自動推定 / 数値(セント) / off")
    args = ap.parse_args()
    stems_dir = args.stems or os.path.splitext(args.out_mid)[0] + "_stems"
    for part in ("vocals", "other"):
        val = getattr(args, part)
        if val:
            onset, frame = (float(x) for x in val.split(","))
            prog, _, _, min_ms, voices, keep = PARTS[part]
            PARTS[part] = (prog, onset, frame, min_ms, voices, keep)

    t = time.time()
    stem_paths = {n: os.path.join(stems_dir, f"{n}.wav") for n in ("vocals", "bass", "drums", "other")}
    if args.reuse_stems and all(os.path.exists(p) for p in stem_paths.values()):
        print(f"分離済みの音声を使います: {stems_dir}", flush=True)
        paths = stem_paths
    else:
        print("Demucsでパート分離中(CPUなので数分かかります)...", flush=True)
        paths = separate(args.wav, stems_dir)
        print(f"  分離完了 {time.time() - t:.0f}秒 -> {stems_dir}", flush=True)

    if args.tune_cents != "off":
        cents = None if args.tune_cents == "auto" else float(args.tune_cents)
        paths = {**paths, **detune_stems(paths, stems_dir, cents)}

    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    for name, (program, onset, frame, min_ms, voices, keep) in PARTS.items():
        _, _, events = predict(paths[name], ICASSP_2022_MODEL_PATH,
                               onset_threshold=onset, frame_threshold=frame,
                               minimum_note_length=min_ms)
        raw = [(s, e, p, a) for s, e, p, a, *_ in events]
        notes = limit_polyphony(raw, voices, keep)
        if voices == 1:
            notes = fix_octaves(notes)
        inst = pretty_midi.Instrument(program=program, name=name)
        for s, e, p, a in notes:
            inst.notes.append(pretty_midi.Note(velocity=int(np.clip(a * 127, 30, 127)),
                                               pitch=int(p), start=float(s), end=float(e)))
        pm.instruments.append(inst)
        print(f"  {name}: 採譜{len(raw)}音 -> 残した{len(notes)}音 (GM{program}, 同時{voices}音まで)", flush=True)

    pm.write(args.out_mid)
    print(f"書き出しました: {args.out_mid}  (全体 {time.time() - t:.0f}秒)")


if __name__ == "__main__":
    main()
