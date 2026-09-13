"""
自動採譜した1トラックのMIDIを、8ボイス向けに「メロディ/和音/ベース」の3パートに組み直す。

自動採譜の結果は、
  - 伸ばしている音が細切れになる(合唱やストリングスのロングトーンが0.2秒ずつに分かれる)
  - 倍音を拾って、同じ音がオクターブ上/12度上に重なる
  - 全部が同じ重さで並ぶので、メロディが和音に埋もれる
という状態になりやすい。ここではそれを次の順で整理する。

  1. 同じ高さの細切れを1本につなぐ
  2. 同時に鳴り始めた、より強い音のオクターブ/12度/2オクターブ上にある弱い音を倍音とみなして捨てる
  3. 各時刻で一番高い音をメロディ(単音)として抜き出す
  4. 残りから一番低い音をベース(単音)、それ以外を和音(同時 --harmony 音まで)にする

使い方(tools/.venv-transcribe の python で実行):
  python midi_arrange.py 入力.mid 出力.mid [--melody-program 81] [--harmony-program 48]
         [--bass-program 32] [--harmony 2] [--gap-ms 120] [--split 55]
  出力は ch1=メロディ, ch2=和音, ch3=ベース。midi2spc では --lead-channels 1 を付ける
"""
import argparse

import pretty_midi

ONSET_WIN = 0.05       # これ以内に鳴り始めた音は「同時」とみなす
OVERTONES = (12, 19, 24)


def merge_fragments(notes, gap):
    """同じ高さで、前の音の終わりから gap 秒以内に始まる音をつなぐ。"""
    last = {}
    merged = []
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


def drop_overtones(notes):
    keep = []
    for n in notes:
        ghost = any(abs(o.start - n.start) <= ONSET_WIN and n.pitch - o.pitch in OVERTONES
                    and o.velocity >= n.velocity for o in notes if o is not n)
        if not ghost:
            keep.append(n)
    return keep


def monophonic(notes, pick):
    """同時に鳴っている音から pick(候補) で1つ選び、重なりは後の音の頭で切る。"""
    line = []
    for n in sorted(notes, key=lambda n: (n.start, -n.pitch)):
        if line and n.start < line[-1].end:
            cur = line[-1]
            if abs(n.start - cur.start) <= ONSET_WIN:
                if pick(n, cur) is n:
                    line[-1] = n          # 同時に鳴り始めた中で、選ばれた方だけ残す
                continue
            if pick(n, cur) is not n:
                continue
            cur.end = n.start
        line.append(n)
    return [n for n in line if n.end - n.start > 0.04]


def overlaps(a, b):
    return a.start < b.end and b.start < a.end


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("in_mid")
    ap.add_argument("out_mid")
    ap.add_argument("--melody-program", type=int, default=81)
    ap.add_argument("--harmony-program", type=int, default=48)
    ap.add_argument("--bass-program", type=int, default=32)
    ap.add_argument("--harmony", type=int, default=2, help="和音パートの同時発音数")
    ap.add_argument("--gap-ms", type=int, default=120, help="細切れをつなぐ隙間の上限")
    ap.add_argument("--split", type=int, default=55, help="この音より下だけをベース候補にする(MIDIノート番号)")
    args = ap.parse_args()

    src = pretty_midi.PrettyMIDI(args.in_mid)
    raw = [n for inst in src.instruments if not inst.is_drum for n in inst.notes]
    notes = drop_overtones(merge_fragments(raw, args.gap_ms / 1000))

    # メロディは --split 以上の音からだけ選ぶ(伴奏しか鳴っていない所でベースをメロディにしない)
    melody = monophonic([n for n in notes if n.pitch >= args.split],
                        lambda a, b: a if a.pitch > b.pitch else b)
    mel_ids = {id(n) for n in melody}
    rest = [n for n in notes if id(n) not in mel_ids]

    bass = monophonic([n for n in rest if n.pitch < args.split],
                      lambda a, b: a if a.pitch < b.pitch else b)
    bass_ids = {id(n) for n in bass}
    rest = [n for n in rest if id(n) not in bass_ids]

    # 和音: メロディより上に出る音は捨て、同時発音数を制限(強い音を優先)
    harmony = []
    for n in sorted(rest, key=lambda n: (n.start, -n.velocity)):
        if any(overlaps(n, m) and n.pitch >= m.pitch for m in melody):
            continue
        if sum(1 for h in harmony if overlaps(n, h)) >= args.harmony:
            continue
        harmony.append(n)

    out = pretty_midi.PrettyMIDI(initial_tempo=120)
    for name, prog, part, vel_boost in (("melody", args.melody_program, melody, 20),
                                        ("harmony", args.harmony_program, harmony, -10),
                                        ("bass", args.bass_program, bass, 0)):
        inst = pretty_midi.Instrument(program=prog, name=name)
        for n in part:
            inst.notes.append(pretty_midi.Note(max(1, min(127, n.velocity + vel_boost)),
                                               n.pitch, n.start, n.end))
        out.instruments.append(inst)
        ps = [n.pitch for n in part] or [0]
        print(f"  {name:7s}: {len(part):4d}音 音域{min(ps)}-{max(ps)} (GM{prog})")
    out.write(args.out_mid)
    print(f"採譜{len(raw)}音 -> 整理後{len(notes)}音 -> 書き出し {args.out_mid}")


if __name__ == "__main__":
    main()
