#!/usr/bin/env python3
"""
engine.py - MIDIイベント列 → S-DSPレジスタ操作イベント列

このモジュールが「MIDIをSPC(SHVC-SOUND)に変換する」中核。
出力は S-DSP の8ボイスに対する操作の時系列で、これはそのまま
実機のSHVC-SOUNDに送りつけるコマンド列に相当する。

つまり:
    MIDI --(engine)--> DspEvent列 --(render)--> PC上の音
                                 \\-(将来)---> Arduino経由で実チップ

S-DSPの制約:
  * 同時発音は8ボイスまで(足りなければ音を奪う)
  * 音量は符号付き8bit (-128..127)、左右独立(VOLL/VOLR)
  * ピッチは14bit (PITCHレジスタ)。値4096で「元のサンプルレートどおり」
  * エンベロープはADSR(AR/DR/SL/SR)
"""

from dataclasses import dataclass, field

from . import instruments


NUM_VOICES = 8
DRUM_CHANNEL = 9          # MIDIチャンネル10 (0始まりで9)
PITCH_MAX = 16383         # PITCHレジスタは14bit
PITCH_UNITY = 4096        # 比1.0に相当する値


# ---- 出力イベント -----------------------------------------------------------

@dataclass
class KeyOn:
    time: float
    voice: int
    instrument: str       # 実機ではSRCN(サンプル番号)になる
    pitch: int            # PITCHレジスタ値
    voll: int             # -128..127
    volr: int
    adsr1: int
    adsr2: int


@dataclass
class KeyOff:
    time: float
    voice: int


@dataclass
class SetPitch:
    time: float
    voice: int
    pitch: int


@dataclass
class SetVolume:
    time: float
    voice: int
    voll: int
    volr: int


# ---- 内部状態 ---------------------------------------------------------------

@dataclass
class _ChannelState:
    program: int = 0
    volume: int = 100      # CC7
    expression: int = 127  # CC11
    pan: int = 64          # CC10 (64が中央)
    bend: int = 0          # -8192..8191
    bend_range: float = 2.0  # 半音単位。RPN未対応なので固定
    sustain: bool = False  # CC64


@dataclass
class _VoiceState:
    active: bool = False
    channel: int = -1
    note: int = -1
    instrument: str = ""
    start_time: float = 0.0
    velocity: int = 0
    held_by_pedal: bool = False
    base_hz: float = 0.0
    natural_hz: float = 1.0
    last_pitch: int = 0
    last_vol: tuple = field(default=(0, 0))


def note_to_hz(note, bend_semitones=0.0):
    """MIDIノート番号を周波数に変換する(A4=440Hz)。"""
    return 440.0 * (2.0 ** ((note + bend_semitones - 69) / 12.0))


def _pitch_register(hz, natural_hz):
    """再生周波数とサンプルの素の周波数から、PITCHレジスタ値を求める。"""
    value = int(round(PITCH_UNITY * hz / natural_hz))
    return max(1, min(PITCH_MAX, value))


def _volume_pair(velocity, ch: _ChannelState, master=1.0):
    """
    ベロシティ・CC7・CC11・パンから VOLL/VOLR を計算する。

    S-DSPの音量は符号付き8bitなので最大127。複数ボイスが同時に鳴ると
    加算で飽和しやすいため、master で全体を絞れるようにしてある。
    """
    amp = (velocity / 127.0) * (ch.volume / 127.0) * (ch.expression / 127.0) * master
    amp = max(0.0, min(1.0, amp))

    # 等パワーパン(中央でも音量が落ち込まないように)
    pan = max(0, min(127, ch.pan)) / 127.0
    left = (1.0 - pan) ** 0.5
    right = pan ** 0.5

    voll = int(round(127 * amp * left))
    volr = int(round(127 * amp * right))
    return max(-128, min(127, voll)), max(-128, min(127, volr))


# ---- 変換本体 ---------------------------------------------------------------

class Sequencer:
    """MIDIイベントを受け取り、DSPイベント列を組み立てる。"""

    def __init__(self, bank, master_volume=0.55, drum_channel=DRUM_CHANNEL):
        self.bank = bank
        self.master = master_volume
        self.drum_channel = drum_channel
        self.channels = [_ChannelState() for _ in range(16)]
        self.voices = [_VoiceState() for _ in range(NUM_VOICES)]
        self.events = []
        self.stolen = 0
        self.notes_played = 0

    # -- ボイス割り当て --
    def _allocate(self, time):
        """
        空きボイスを探す。全部埋まっていたら一番古く鳴り始めたものを奪う。
        実機と同じく8音までしか鳴らせないので、この「音の奪い合い」は
        SNESらしさの一部でもある。
        """
        for i, v in enumerate(self.voices):
            if not v.active:
                return i
        oldest = min(range(NUM_VOICES), key=lambda i: self.voices[i].start_time)
        self.events.append(KeyOff(time, oldest))
        self.voices[oldest].active = False
        self.stolen += 1
        return oldest

    def _find_voice(self, channel, note):
        for i, v in enumerate(self.voices):
            if v.active and v.channel == channel and v.note == note:
                return i
        return None

    # -- MIDIイベント処理 --
    def note_on(self, time, channel, note, velocity):
        ch = self.channels[channel]

        if channel == self.drum_channel:
            name = instruments.DRUM_NOTE_TO_NAME.get(note, "tom")
            inst = self.bank.get(name)
            if inst is None:
                return
            # 打楽器はサンプルをそのままの速さで鳴らすのが基本。
            # タム類だけはノート番号で音程を変えて表情をつける。
            if name == "tom":
                base_hz = inst.natural_hz * (2.0 ** ((note - 45) / 24.0))
            else:
                base_hz = inst.natural_hz
            bend = 0.0
        else:
            name = instruments.GM_PROGRAM_TO_NAME.get(ch.program, "piano")
            inst = self.bank.get(name)
            if inst is None:
                return
            bend = (ch.bend / 8192.0) * ch.bend_range
            base_hz = note_to_hz(note, bend)

        # 同じチャンネル・同じ音が鳴りっぱなしなら先に止める
        existing = self._find_voice(channel, note)
        if existing is not None:
            self.events.append(KeyOff(time, existing))
            self.voices[existing].active = False

        vi = self._allocate(time)
        pitch = _pitch_register(base_hz, inst.natural_hz)
        voll, volr = _volume_pair(velocity, ch, self.master)

        v = self.voices[vi]
        v.active = True
        v.channel = channel
        v.note = note
        v.instrument = name
        v.start_time = time
        v.velocity = velocity
        v.held_by_pedal = False
        v.base_hz = base_hz
        v.natural_hz = inst.natural_hz
        v.last_pitch = pitch
        v.last_vol = (voll, volr)

        self.events.append(KeyOn(time, vi, name, pitch, voll, volr, inst.adsr1, inst.adsr2))
        self.notes_played += 1

    def note_off(self, time, channel, note):
        vi = self._find_voice(channel, note)
        if vi is None:
            return
        if self.channels[channel].sustain:
            # サステインペダル中は離鍵しても鳴らし続ける
            self.voices[vi].held_by_pedal = True
            return
        self.events.append(KeyOff(time, vi))
        self.voices[vi].active = False

    def control_change(self, time, channel, controller, value):
        ch = self.channels[channel]
        if controller == 7:
            ch.volume = value
            self._refresh_volumes(time, channel)
        elif controller == 11:
            ch.expression = value
            self._refresh_volumes(time, channel)
        elif controller == 10:
            ch.pan = value
            self._refresh_volumes(time, channel)
        elif controller == 64:
            was = ch.sustain
            ch.sustain = value >= 64
            if was and not ch.sustain:
                # ペダルを離した: 保留していた音を一斉に止める
                for vi, v in enumerate(self.voices):
                    if v.active and v.channel == channel and v.held_by_pedal:
                        self.events.append(KeyOff(time, vi))
                        v.active = False
        elif controller == 120 or controller == 123:
            # All Sound Off / All Notes Off
            for vi, v in enumerate(self.voices):
                if v.active and v.channel == channel:
                    self.events.append(KeyOff(time, vi))
                    v.active = False

    def program_change(self, time, channel, program):
        self.channels[channel].program = program

    def pitch_bend(self, time, channel, value):
        ch = self.channels[channel]
        ch.bend = value
        if channel == self.drum_channel:
            return
        semitones = (value / 8192.0) * ch.bend_range
        for vi, v in enumerate(self.voices):
            if v.active and v.channel == channel:
                hz = note_to_hz(v.note, semitones)
                pitch = _pitch_register(hz, v.natural_hz)
                if pitch != v.last_pitch:
                    v.last_pitch = pitch
                    self.events.append(SetPitch(time, vi, pitch))

    def _refresh_volumes(self, time, channel):
        ch = self.channels[channel]
        for vi, v in enumerate(self.voices):
            if v.active and v.channel == channel:
                voll, volr = _volume_pair(v.velocity, ch, self.master)
                if (voll, volr) != v.last_vol:
                    v.last_vol = (voll, volr)
                    self.events.append(SetVolume(time, vi, voll, volr))


def convert(midi_events, bank, master_volume=0.55):
    """
    MIDIイベント列(smf.parse_midi の出力)をDSPイベント列に変換する。
    戻り値は (イベント列, 統計情報dict)。
    """
    from .smf import NoteOn, NoteOff, ControlChange, ProgramChange, PitchBend

    seq = Sequencer(bank, master_volume=master_volume)
    for ev in midi_events:
        if isinstance(ev, NoteOn):
            seq.note_on(ev.time, ev.channel, ev.note, ev.velocity)
        elif isinstance(ev, NoteOff):
            seq.note_off(ev.time, ev.channel, ev.note)
        elif isinstance(ev, ControlChange):
            seq.control_change(ev.time, ev.channel, ev.controller, ev.value)
        elif isinstance(ev, ProgramChange):
            seq.program_change(ev.time, ev.channel, ev.program)
        elif isinstance(ev, PitchBend):
            seq.pitch_bend(ev.time, ev.channel, ev.value)

    # 最後に鳴りっぱなしのボイスを止める
    end_time = max((ev.time for ev in seq.events), default=0.0)
    for vi, v in enumerate(seq.voices):
        if v.active:
            seq.events.append(KeyOff(end_time, vi))
            v.active = False

    seq.events.sort(key=lambda e: e.time)
    stats = {
        "notes": seq.notes_played,
        "stolen": seq.stolen,
        "events": len(seq.events),
        "duration": end_time,
    }
    return seq.events, stats
