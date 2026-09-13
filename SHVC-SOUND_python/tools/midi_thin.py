"""
自動採譜したMIDIの音数を、曲全体で均等に間引く(1トラックのまま、音色も変えない)。

自動採譜は
  - 同じ音を細切れに何度も鳴らし直す
  - 倍音を拾って、同じ音をオクターブ上/12度上/2オクターブ上に重ねる
  - 同じタイミングに音を詰め込みすぎる
ので、「音を重ねて表現している」ように聞こえる。これを次の順で整理する。

  1. 同じ高さで、隙間 --gap-ms 以内に続く細切れを1本につなぐ
  2. 同時に鳴り始めた、より強い音のオクターブ/12度/2オクターブ上(と同音)にある弱い音を捨てる
  3. 同時に鳴っている音を --voices 音までに制限する。
     一番高い音(メロディ)と一番低い音(ベース)は必ず残し、間の音は強いものから残す
  4. 弱すぎる音(ベロシティ下位 --quiet パーセント)を捨てる

使い方(tools/.venv-transcribe の python で実行):
  python midi_thin.py 入力.mid 出力.mid [--voices 4] [--gap-ms 80] [--quiet 15]
"""
import argparse

import numpy as np
import pretty_midi

ONSET_WIN = 0.05
OVERTONES = (0, 12, 19, 24)


def merge_fragments(notes, gap):
    last, merged = {}, []
    for n in sorted(notes, key=lambda n: n.start):
        prev = last.get(n.pitch)
        if prev is not None and n.start - prev.end <= gap:
            prev.end = max(prev.end, n.end)
            prev.velocity = max(prev.velocity, n.velocity)
            continue
        m = pretty_midi.Note(n.velocity, n.pitch, n.start, n.end)
        last[n.pitch] = m
        merged.append(m)
    return sorted(merged, key=lambda n: (n.start, n.pitch))


def drop_doublings(notes):
    keep = []
    for n in notes:
        doubled = any(o is not n and abs(o.start - n.start) <= ONSET_WIN
                      and n.pitch - o.pitch in OVERTONES
                      and (o.velocity, -o.pitch) > (n.velocity, -n.pitch)
                      for o in notes)
        if not doubled:
            keep.append(n)
    return keep


def limit_voices(notes, voices):
    """鳴り始めの時刻ごとに、そのとき鳴っている音を voices 音以下にする。"""
    kept = []
    for n in sorted(notes, key=lambda n: (n.start, -n.velocity)):
        sounding = [k for k in kept if k.end > n.start]
        if len(sounding) < voices:
            kept.append(n)
            continue
        pool = sounding + [n]
        top = max(pool, key=lambda k: k.pitch)
        bottom = min(pool, key=lambda k: k.pitch)
        middle = [k for k in pool if k is not top and k is not bottom]
        victim = min(middle, key=lambda k: k.velocity) if middle else None
        if victim is None or victim is n:
            continue
        victim.end = n.start               # 鳴っていた弱い音を、新しい音の頭で止める
        kept.append(n)
    return [k for k in kept if k.end - k.start > 0.04]


def max_poly(notes):
    ev = sorted([(n.start, 1) for n in notes] + [(n.end, -1) for n in notes])
    cur = mx = 0
    for _, d in ev:
        cur += d
        mx = max(mx, cur)
    return mx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_mid")
    ap.add_argument("out_mid")
    ap.add_argument("--voices", type=int, default=4, help="同時に鳴らす音数の上限")
    ap.add_argument("--gap-ms", type=int, default=-1,
                    help="細切れをつなぐ隙間の上限。既定(-1)はつながない。"
                         "Basic Pitchは同じ音の連打を隙間0で並べて出すので、つなぐとリズムが消える")
    ap.add_argument("--quiet", type=float, default=15, help="捨てる弱い音の割合(パーセント)")
    args = ap.parse_args()

    src = pretty_midi.PrettyMIDI(args.in_mid)
    inst0 = src.instruments[0]
    raw = [n for inst in src.instruments if not inst.is_drum for n in inst.notes]

    if args.gap_ms >= 0:
        s1 = merge_fragments(raw, args.gap_ms / 1000)
    else:
        s1 = sorted((pretty_midi.Note(n.velocity, n.pitch, n.start, n.end) for n in raw),
                    key=lambda n: (n.start, n.pitch))
    s2 = drop_doublings(s1)
    if args.quiet > 0 and s2:
        cut = np.percentile([n.velocity for n in s2], args.quiet)
        s3 = [n for n in s2 if n.velocity >= cut]
    else:
        s3 = s2
    s4 = limit_voices(s3, args.voices)

    out = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=inst0.program, name="thinned")
    inst.notes = sorted(s4, key=lambda n: n.start)
    out.instruments.append(inst)
    out.write(args.out_mid)

    print(f"元 {len(raw)}音 (同時最大{max_poly(raw)})")
    print(f"  細切れをつないで  {len(s1)}音")
    print(f"  重ね(同音/オクターブ/12度)を除いて {len(s2)}音")
    print(f"  弱い音を除いて    {len(s3)}音")
    print(f"  同時{args.voices}音に制限して {len(s4)}音 (同時最大{max_poly(s4)})")
    print(f"書き出しました: {args.out_mid}")


if __name__ == "__main__":
    main()
