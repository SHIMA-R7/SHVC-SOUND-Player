"""
録音から「楽譜を起こすように」メロディと和音を取り出し、8ボイス向けのMIDIにする。

音符をそのまま検出する(Basic Pitchのノート出力)のではなく、
  1. 拍を検出して、1拍を --subdiv 等分した升目(8分音符など)を作る
  2. 各升目で「一番高く、はっきり鳴っている音」をメロディとして1つだけ選ぶ
     (Basic Pitchの音高ごとの鳴っている度合いを使い、オクターブ上の倍音は除外)
  3. 曲のキーを推定し、メロディを音階の音に寄せる
  4. 同じ高さが続く升目は、発音し直しがなければ1つの長い音にまとめる(伸ばす音を細切れにしない)
  5. 拍ごとに響き(クロマ)から和音(長三和音/短三和音)を判定し、和音とベースを付ける
という手順で、升目にそろったメロディ・和音・ベースの3パートを作る。

出力: ch1=メロディ, ch2=和音(3声), ch3=ベース。midi2spc では --lead-channels 1 を付ける。

使い方(tools/.venv-transcribe の python で実行。チューニング補正済みのWAVを推奨):
  python score_transcribe.py 入力.wav 出力.mid [--subdiv 2] [--low 55] [--high 91]
"""
import argparse

import librosa
import numpy as np
import pretty_midi
from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict
from basic_pitch.note_creation import model_frames_to_time

MIDI_OFFSET = 21        # Basic Pitchの音高出力の0番目 = A0(27.5Hz) = MIDIノート21
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
# Krumhanslのキープロファイル
KP_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KP_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def estimate_key(chroma_total):
    best = None
    for tonic in range(12):
        for mode, prof in (("major", KP_MAJOR), ("minor", KP_MINOR)):
            score = np.corrcoef(chroma_total, np.roll(prof, tonic))[0, 1]
            if best is None or score > best[0]:
                best = (score, tonic, mode)
    _, tonic, mode = best
    rel_major = tonic if mode == "major" else (tonic + 3) % 12   # 短調は平行長調の音階を使う
    scale = {(rel_major + s) % 12 for s in MAJOR}
    return tonic, mode, scale


def snap_to_scale(p, scale):
    if p % 12 in scale:
        return p
    for d in (1, -1):
        if (p + d) % 12 in scale:
            return p + d
    return p


def melody_frames(note_post, low, high, thr, rel=0.5, overtone_ratio=1.8):
    """
    フレームごとに (メロディの音高, 強さ) を返す。鳴っていなければ (-1, 0)。

    高い音ほどBasic Pitchの「鳴っている度合い」は小さく出る(合唱のソプラノ等)。
    固定の閾値だと高音域がまるごと消えるので、そのフレームで一番強い音の rel 倍以上を
    「鳴っている」とみなす(ただし thr 未満は無音扱い)。
    メロディは下のオクターブで重ねられることが多いので、倍音とみなすのは
    1オクターブ下/12度下が overtone_ratio 倍以上はっきり強いときだけにする。
    """
    lo, hi = low - MIDI_OFFSET, high - MIDI_OFFSET + 1
    out_p = np.full(len(note_post), -1)
    out_v = np.zeros(len(note_post))
    for i, frame in enumerate(note_post):
        peak = frame[lo:hi].max()
        if peak < thr:
            continue
        floor = max(thr, peak * rel)
        for b in range(hi - 1, lo - 1, -1):
            v = frame[b]
            if v < floor:
                continue
            if (b - 12 >= 0 and frame[b - 12] > v * overtone_ratio) or \
               (b - 19 >= 0 and frame[b - 19] > v * overtone_ratio * 1.2):
                continue
            out_p[i] = b + MIDI_OFFSET
            out_v[i] = v
            break
    return out_p, out_v


def build_grid(beats, subdiv, end_time):
    grid = []
    for a, b in zip(beats, beats[1:]):
        for k in range(subdiv):
            grid.append(a + (b - a) * k / subdiv)
    if len(beats) >= 2:
        step = (beats[-1] - beats[-2]) / subdiv
        t = beats[-1]
        while t < end_time:
            grid.append(t)
            t += step
    grid.append(end_time)
    return np.array(grid)


CHORDS = []
for root in range(12):
    for quality, ivs in (("", (0, 4, 7)), ("m", (0, 3, 7))):
        tmpl = np.zeros(12)
        tmpl[[(root + i) % 12 for i in ivs]] = 1.0
        CHORDS.append((root, quality, ivs, tmpl / np.linalg.norm(tmpl)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("out_mid")
    ap.add_argument("--subdiv", type=int, default=2, help="1拍を何等分するか(2=8分音符)")
    ap.add_argument("--low", type=int, default=55, help="メロディの最低音(MIDIノート番号)")
    ap.add_argument("--high", type=int, default=91, help="メロディの最高音")
    ap.add_argument("--thr", type=float, default=0.12, help="これ未満は無音とみなす強さ")
    ap.add_argument("--rel", type=float, default=0.5,
                    help="そのフレームで一番強い音の何倍以上を「鳴っている」とみなすか")
    ap.add_argument("--overtone-ratio", type=float, default=1.8,
                    help="下のオクターブがこの倍以上強いときだけ倍音として除外")
    ap.add_argument("--no-snap", action="store_true", help="音階への寄せをしない")
    ap.add_argument("--melody-wav", default=None,
                    help="メロディだけ別の音声(Demucsで分離したボーカル等)から拾う。拍と和音は入力WAVから")
    args = ap.parse_args()

    y, sr = librosa.load(args.wav, sr=22050, mono=True)
    duration = len(y) / sr

    # 1. 拍
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time", trim=False)
    tempo = float(np.atleast_1d(tempo)[0])
    grid = build_grid(beats, args.subdiv, duration)
    print(f"テンポ約{tempo:.0f}BPM 拍{len(beats)}個 升目{len(grid) - 1}個(1拍{args.subdiv}分割)")

    # 2. キー
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=512)
    tonic, mode, scale = estimate_key(chroma.sum(axis=1))
    print(f"推定キー {NAMES[tonic]} {'メジャー' if mode == 'major' else 'マイナー'}")

    # 3. 升目ごとのメロディ
    model_output, _, _ = predict(args.melody_wav or args.wav, ICASSP_2022_MODEL_PATH)
    note_post, onset_post = model_output["note"], model_output["onset"]
    ftimes = model_frames_to_time(len(note_post))
    mp, mv = melody_frames(note_post, args.low, args.high, args.thr, args.rel, args.overtone_ratio)

    cells = []
    for a, b in zip(grid, grid[1:]):
        idx = np.where((ftimes >= a) & (ftimes < b))[0]
        if len(idx) == 0:
            cells.append((-1, 0.0, False))
            continue
        votes = {}
        for i in idx:
            if mp[i] > 0:
                votes[mp[i]] = votes.get(mp[i], 0.0) + mv[i]
        if not votes:
            cells.append((-1, 0.0, False))
            continue
        p, w = max(votes.items(), key=lambda kv: kv[1])
        covered = sum(1 for i in idx if mp[i] > 0) / len(idx)
        if covered < 0.4:
            cells.append((-1, 0.0, False))
            continue
        if not args.no_snap:
            p = snap_to_scale(int(p), scale)
        head = idx[: max(1, len(idx) // 3)]
        b_ = int(p) - MIDI_OFFSET
        onset = bool(0 <= b_ < onset_post.shape[1] and onset_post[head, b_].max() > 0.5)
        cells.append((int(p), w / len(idx), onset))

    # 4. 升目をつないで音符にする
    melody = []
    for k, (p, w, onset) in enumerate(cells):
        a, b = grid[k], grid[k + 1]
        if p < 0:
            continue
        if melody and melody[-1][2] == p and abs(melody[-1][1] - a) < 1e-6 and not onset:
            melody[-1][1] = b
            melody[-1][3] = max(melody[-1][3], w)
        else:
            melody.append([a, b, p, w])

    # 5. 拍ごとの和音(直前の和音と大差なければ維持して、ちらつきを防ぐ)
    ctimes = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr, hop_length=512)
    chord_spans = []
    prev = None
    edges = list(beats) + [duration]
    for a, b in zip(edges, edges[1:]):
        sel = (ctimes >= a) & (ctimes < b)
        if not sel.any():
            continue
        c = chroma[:, sel].mean(axis=1)
        c = c / (np.linalg.norm(c) + 1e-9)
        scores = [(float(c @ t) + (0.05 if (r % 12) in scale else 0.0), r, q, ivs)
                  for r, q, ivs, t in CHORDS]
        best = max(scores)
        if prev is not None:
            prev_score = next(s for s in scores if s[1] == prev[1] and s[2] == prev[2])
            if best[0] < prev_score[0] + 0.05:
                best = prev_score
        if chord_spans and chord_spans[-1][2] == best[1] and chord_spans[-1][3] == best[2]:
            chord_spans[-1][1] = b
        else:
            chord_spans.append([a, b, best[1], best[2], best[3]])
        prev = best

    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    mel = pretty_midi.Instrument(program=81, name="melody")
    for a, b, p, w in melody:
        mel.notes.append(pretty_midi.Note(int(np.clip(70 + w * 60, 70, 120)), p, a, b))
    har = pretty_midi.Instrument(program=48, name="harmony")
    bas = pretty_midi.Instrument(program=32, name="bass")
    for a, b, root, _, ivs in chord_spans:
        base = 48 + root                                   # C3〜B3に根音を置いた三和音
        for iv in ivs:
            har.notes.append(pretty_midi.Note(55, base + iv, a, b))
        bas.notes.append(pretty_midi.Note(80, 36 + root, a, b))
    pm.instruments.extend([mel, har, bas])
    pm.write(args.out_mid)

    names = [NAMES[r] + q for _, _, r, q, _ in chord_spans]
    print(f"メロディ {len(melody)}音 / 和音 {len(chord_spans)}区間 (種類: {len(set(names))})")
    print(f"書き出しました: {args.out_mid}")


if __name__ == "__main__":
    main()
