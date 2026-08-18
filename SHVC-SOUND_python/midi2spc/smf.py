#!/usr/bin/env python3
"""
smf.py - 標準MIDIファイル(SMF)パーサ

外部ライブラリに依存しない最小実装。Format 0/1 に対応する。
テンポマップを適用して、全トラックをマージした「秒単位の絶対時刻つき
イベント列」を返すところまでを担当する。
"""

import struct
from dataclasses import dataclass


# ---- MIDIイベント(パース結果) --------------------------------------------

@dataclass
class NoteOn:
    time: float          # 秒
    channel: int         # 0-15
    note: int            # 0-127
    velocity: int        # 1-127 (0はNoteOffに変換済み)


@dataclass
class NoteOff:
    time: float
    channel: int
    note: int


@dataclass
class ControlChange:
    time: float
    channel: int
    controller: int
    value: int


@dataclass
class ProgramChange:
    time: float
    channel: int
    program: int         # 0-127 (GM音色番号)


@dataclass
class PitchBend:
    time: float
    channel: int
    value: int           # -8192..8191 (センターが0)


class MidiParseError(Exception):
    pass


# ---- 可変長数値・チャンク読み ----------------------------------------------

def _read_varlen(data: bytes, pos: int):
    """SMFの可変長数値を読む。(値, 次の位置) を返す。"""
    value = 0
    for _ in range(4):
        if pos >= len(data):
            raise MidiParseError("可変長数値の途中でデータが尽きました")
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not (byte & 0x80):
            return value, pos
    raise MidiParseError("可変長数値が4バイトを超えています")


def _split_chunks(data: bytes):
    """ファイル全体を (チャンクID, 中身) のリストに分解する。"""
    chunks = []
    pos = 0
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        (length,) = struct.unpack(">I", data[pos + 4:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if len(body) != length:
            # 長さが壊れているファイルは、読める分だけ拾って打ち切る
            chunks.append((cid, body))
            break
        chunks.append((cid, body))
        pos += 8 + length
    return chunks


# ---- トラック単体のパース(tick単位) ---------------------------------------

def _parse_track(body: bytes):
    """
    1トラックを (tick, 種別, パラメータ...) のリストにする。
    種別は 'note_on'/'note_off'/'cc'/'program'/'bend'/'tempo'。
    """
    events = []
    pos = 0
    tick = 0
    running_status = None

    while pos < len(body):
        delta, pos = _read_varlen(body, pos)
        tick += delta
        if pos >= len(body):
            break

        status = body[pos]
        if status & 0x80:
            pos += 1
            if status < 0xF0:
                running_status = status
        else:
            # ランニングステータス: 直前のステータスバイトを流用する
            if running_status is None:
                raise MidiParseError(f"ランニングステータスが未確定です (pos={pos})")
            status = running_status

        kind = status & 0xF0
        channel = status & 0x0F

        if status == 0xFF:
            # メタイベント
            meta_type = body[pos]
            pos += 1
            length, pos = _read_varlen(body, pos)
            payload = body[pos:pos + length]
            pos += length
            if meta_type == 0x51 and len(payload) == 3:
                usec_per_beat = (payload[0] << 16) | (payload[1] << 8) | payload[2]
                events.append((tick, "tempo", usec_per_beat))
            elif meta_type == 0x2F:
                break  # End of Track
        elif status in (0xF0, 0xF7):
            # SysEx: 読み飛ばす
            length, pos = _read_varlen(body, pos)
            pos += length
        elif kind == 0x80:
            note, vel = body[pos], body[pos + 1]
            pos += 2
            events.append((tick, "note_off", channel, note, vel))
        elif kind == 0x90:
            note, vel = body[pos], body[pos + 1]
            pos += 2
            # ベロシティ0のNoteOnはNoteOffと同じ意味
            if vel == 0:
                events.append((tick, "note_off", channel, note, 0))
            else:
                events.append((tick, "note_on", channel, note, vel))
        elif kind == 0xA0:
            pos += 2  # ポリフォニックアフタータッチ: 未対応
        elif kind == 0xB0:
            ctrl, val = body[pos], body[pos + 1]
            pos += 2
            events.append((tick, "cc", channel, ctrl, val))
        elif kind == 0xC0:
            program = body[pos]
            pos += 1
            events.append((tick, "program", channel, program))
        elif kind == 0xD0:
            pos += 1  # チャンネルアフタータッチ: 未対応
        elif kind == 0xE0:
            lsb, msb = body[pos], body[pos + 1]
            pos += 2
            events.append((tick, "bend", channel, ((msb << 7) | lsb) - 8192))
        else:
            raise MidiParseError(f"未知のステータスバイト 0x{status:02X} (pos={pos})")

    return events


# ---- tick → 秒 の変換 -------------------------------------------------------

def _build_time_converter(tempo_events, division):
    """
    テンポチェンジを積み上げて、tick を秒に変換する関数を作って返す。

    division が正なら「4分音符あたりのtick数」、負なら SMPTE 形式。
    """
    if division & 0x8000:
        # SMPTE: 上位バイトがフレームレート(負数)、下位がフレーム内分解能
        frames_per_sec = 256 - (division >> 8)
        ticks_per_frame = division & 0xFF
        ticks_per_sec = frames_per_sec * ticks_per_frame
        return lambda tick: tick / ticks_per_sec

    ticks_per_beat = division
    # (開始tick, その時点の開始秒, 1tickあたりの秒数) の区間リスト
    segments = [(0, 0.0, 0.5 / ticks_per_beat)]  # 初期テンポは120BPM
    for tick, usec_per_beat in sorted(tempo_events):
        start_tick, start_sec, sec_per_tick = segments[-1]
        if tick == start_tick:
            segments[-1] = (start_tick, start_sec, (usec_per_beat / 1e6) / ticks_per_beat)
        else:
            new_sec = start_sec + (tick - start_tick) * sec_per_tick
            segments.append((tick, new_sec, (usec_per_beat / 1e6) / ticks_per_beat))

    def to_seconds(tick):
        # 区間数はふつう少ないので線形探索で十分
        seg = segments[0]
        for candidate in segments:
            if candidate[0] <= tick:
                seg = candidate
            else:
                break
        start_tick, start_sec, sec_per_tick = seg
        return start_sec + (tick - start_tick) * sec_per_tick

    return to_seconds


# ---- 公開API ----------------------------------------------------------------

def parse_midi(path):
    """
    SMFを読み、秒単位の絶対時刻がついたイベントのリストを時刻順で返す。
    """
    with open(path, "rb") as f:
        data = f.read()

    chunks = _split_chunks(data)
    if not chunks or chunks[0][0] != b"MThd":
        raise MidiParseError("MThdヘッダが見つかりません(MIDIファイルではないかも)")

    header = chunks[0][1]
    if len(header) < 6:
        raise MidiParseError("MThdヘッダが短すぎます")
    fmt, ntracks, division = struct.unpack(">HHH", header[:6])
    if fmt not in (0, 1, 2):
        raise MidiParseError(f"未知のSMFフォーマット: {fmt}")

    tracks = [_parse_track(body) for cid, body in chunks[1:] if cid == b"MTrk"]
    if not tracks:
        raise MidiParseError("MTrkトラックが1つもありません")

    # テンポは(慣例上)どのトラックに書かれていても曲全体に効く
    tempo_events = [(ev[0], ev[2]) for track in tracks for ev in track if ev[1] == "tempo"]
    to_seconds = _build_time_converter(tempo_events, division)

    # 全トラックをtick順にマージする。
    # 同一tickではトラック順・出現順を保つ(安定ソート)。
    merged = []
    for track in tracks:
        merged.extend(track)
    merged.sort(key=lambda ev: ev[0])

    out = []
    for ev in merged:
        tick, kind = ev[0], ev[1]
        t = to_seconds(tick)
        if kind == "note_on":
            out.append(NoteOn(t, ev[2], ev[3], ev[4]))
        elif kind == "note_off":
            out.append(NoteOff(t, ev[2], ev[3]))
        elif kind == "cc":
            out.append(ControlChange(t, ev[2], ev[3], ev[4]))
        elif kind == "program":
            out.append(ProgramChange(t, ev[2], ev[3]))
        elif kind == "bend":
            out.append(PitchBend(t, ev[2], ev[3]))
        # tempoは変換に使い終わったので出力しない

    return out, {"format": fmt, "tracks": ntracks, "division": division}
