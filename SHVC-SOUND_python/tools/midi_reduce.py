"""
MIDIのトラックを選んで、8ボイス向けの軽いMIDIを作る。

MuseScore等のオーケストラ譜の書き出しは、31トラックが16チャンネルを
共有していて、同じチャンネルに複数の音色指定が上書きし合う(オーボエが
弦の音色で鳴る等)。チャンネル単位で外す --drop-channels では切り分けられないので、
トラック単位で残すものを選び、残したトラックにチャンネルと音色を振り直す。

使い方:
  python midi_reduce.py 入力.mid                      # トラック一覧を表示
  python midi_reduce.py 入力.mid 出力.mid 1:73 24:0 22:drum ...
      トラック番号:GM音色番号(0-127) / トラック番号:drum
      書き出し後、各トラックが何チャンネルになったかを表示する
"""
import os
import re
import struct
import sys

PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # SHVC-SOUND_python
sys.path.insert(0, PY_DIR)
from midi2spc.smf import _parse_track, _split_chunks  # noqa: E402

KEEP_CC = {7, 10, 11, 64}   # 音量・パン・エクスプレッション・サステインだけ持ち越す


def track_name(body):
    m = re.search(rb"\xff\x03", body)
    if not m:
        return ""
    length = body[m.end()]
    return body[m.end() + 1:m.end() + 1 + length].decode("utf-8", "replace")


def varlen(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def encode_track(timed):
    """(tick, 生バイト列) のリストをMTrkチャンクにする。"""
    body = bytearray()
    prev = 0
    for tick, raw in sorted(timed, key=lambda x: x[0]):
        body += varlen(tick - prev) + raw
        prev = tick
    body += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(sys.argv) >= 2 else 1
    data = open(sys.argv[1], "rb").read()
    chunks = _split_chunks(data)
    division = struct.unpack(">HHH", chunks[0][1][:6])[2]
    bodies = [b for cid, b in chunks[1:] if cid == b"MTrk"]
    tracks = [_parse_track(b) for b in bodies]

    if len(sys.argv) == 2:
        for i, (body, t) in enumerate(zip(bodies, tracks)):
            notes = [e[3] for e in t if e[1] == "note_on"]
            if notes:
                print(f"T{i:2d} {track_name(body)[:24]:24s} {len(notes):5d}音 音域{min(notes)}-{max(notes)}")
        return 0

    out_path = sys.argv[2]
    tempo = [(e[0], b"\xff\x51\x03" + e[2].to_bytes(3, "big"))
             for t in tracks for e in t if e[1] == "tempo"]
    out_chunks = [encode_track(tempo)]

    free = [c for c in range(16) if c != 9]
    for spec in sys.argv[3:]:
        idx, _, prog = spec.partition(":")
        idx = int(idx)
        if prog == "drum":
            ch = 9
        else:
            ch = free.pop(0)
        timed = []
        if prog != "drum":
            timed.append((0, bytes([0xC0 | ch, int(prog)])))
        for e in tracks[idx]:
            kind = e[1]
            if kind == "note_on":
                timed.append((e[0], bytes([0x90 | ch, e[3], e[4]])))
            elif kind == "note_off":
                timed.append((e[0], bytes([0x80 | ch, e[3], 0x40])))
            elif kind == "cc" and e[3] in KEEP_CC:
                timed.append((e[0], bytes([0xB0 | ch, e[3], e[4]])))
            elif kind == "bend":
                v = e[3] + 8192
                timed.append((e[0], bytes([0xE0 | ch, v & 0x7F, (v >> 7) & 0x7F])))
        out_chunks.append(encode_track(timed))
        print(f"T{idx:2d} {track_name(bodies[idx])[:24]:24s} -> MIDI ch{ch + 1:2d} "
              f"({'ドラム' if prog == 'drum' else 'GM ' + prog})")

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(out_chunks), division)
    with open(out_path, "wb") as f:
        f.write(header + b"".join(out_chunks))
    print(f"書き出しました: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
