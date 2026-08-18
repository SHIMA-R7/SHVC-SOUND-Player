#!/usr/bin/env python3
"""
test_midi2spc.py - midi2spc の自動テスト

実行:
    python test_midi2spc.py

実機がなくても確かめられるところを固めておくのが目的。特に
SPC700常駐ドライバ(hardware.DRIVER_CODE)は手でアセンブルした
生バイト列なので、簡易シミュレータで実際に動かして検証する。
"""

import sys
import unittest

import numpy as np

from midi2spc import brr, engine, hardware, instruments, render, smf


# ============================================================================
# SPC700 簡易シミュレータ
# ============================================================================

class Spc700Sim:
    """
    常駐ドライバの検証に必要な命令だけを実装した最小のSPC700。

    $F4-$F7 はホストとの双方向ポートで、方向ごとに別のラッチになっている
    (SPC700が読むのはホストが書いた値、ホストが読むのはSPC700が書いた値)。
    $F2/$F3 はDSPのアドレス/データレジスタ。
    """

    def __init__(self, code, org):
        self.ram = bytearray(0x10000)
        self.ram[org:org + len(code)] = code
        self.pc = org
        self.a = 0
        self.x = 0
        self.y = 0
        self.zero = False
        self.negative = False
        self.page = 0            # Pフラグ(0なら直接ページは$00xx)

        self.host_to_spc = [0, 0, 0, 0]   # ホストが書いた値(SPC700が読む)
        self.spc_to_host = [0, 0, 0, 0]   # SPC700が書いた値(ホストが読む)
        self.dsp_addr = 0
        self.dsp = bytearray(0x80)
        self.dsp_writes = []

    # -- メモリアクセス --
    def read(self, addr):
        if 0xF4 <= addr <= 0xF7:
            return self.host_to_spc[addr - 0xF4]
        return self.ram[addr]

    def write(self, addr, value):
        value &= 0xFF
        if 0xF4 <= addr <= 0xF7:
            self.spc_to_host[addr - 0xF4] = value
        elif addr == 0xF2:
            self.dsp_addr = value
        elif addr == 0xF3:
            self.dsp[self.dsp_addr & 0x7F] = value
            self.dsp_writes.append((self.dsp_addr & 0x7F, value))
        else:
            self.ram[addr] = value

    def _dp(self, operand):
        return (self.page << 8) | operand

    def _fetch(self):
        v = self.ram[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def _set_nz(self, value):
        self.zero = (value & 0xFF) == 0
        self.negative = bool(value & 0x80)

    def step(self):
        op = self._fetch()

        if op == 0x20:                      # clrp
            self.page = 0
        elif op == 0xCD:                    # mov x,#imm
            self.x = self._fetch()
            self._set_nz(self.x)
        elif op == 0xD8:                    # mov dp,x
            self.write(self._dp(self._fetch()), self.x)
        elif op == 0x3E:                    # cmp x,dp
            value = self.read(self._dp(self._fetch()))
            diff = (self.x - value) & 0x1FF
            self.zero = (diff & 0xFF) == 0
            self.negative = bool(diff & 0x80)
        elif op == 0xF8:                    # mov x,dp
            self.x = self.read(self._dp(self._fetch()))
            self._set_nz(self.x)
        elif op == 0xE4:                    # mov a,dp
            self.a = self.read(self._dp(self._fetch()))
            self._set_nz(self.a)
        elif op == 0xC4:                    # mov dp,a
            self.write(self._dp(self._fetch()), self.a)
        elif op == 0xF0:                    # beq rel
            rel = self._fetch()
            if self.zero:
                self.pc = (self.pc + (rel - 256 if rel >= 128 else rel)) & 0xFFFF
        elif op == 0x2F:                    # bra rel
            rel = self._fetch()
            self.pc = (self.pc + (rel - 256 if rel >= 128 else rel)) & 0xFFFF
        else:
            raise AssertionError(
                f"シミュレータが知らない命令 0x{op:02X} at ${self.pc - 1:04X}")

    def run(self, max_steps=10000):
        for _ in range(max_steps):
            self.step()


class TestResidentDriver(unittest.TestCase):
    """SPC700常駐ドライバ(手でアセンブルしたバイト列)の検証。"""

    def _boot(self):
        sim = Spc700Sim(hardware.DRIVER_CODE, hardware.DRIVER_ADDR)
        # 初期化(clrp / mov x,#0 / mov $F4,x)を実行してループ手前まで進める
        sim.step()
        sim.step()
        sim.step()
        return sim

    def test_driver_initialises_ack_latch(self):
        sim = self._boot()
        self.assertEqual(sim.spc_to_host[0], 0,
                         "起動時にACKラッチが0に初期化されていない")
        self.assertEqual(sim.x, 0)

    def test_driver_idles_without_command(self):
        """ホストが何も書かなければ、DSPには一切書かずに回り続けること。"""
        sim = self._boot()
        for _ in range(500):
            sim.step()
        self.assertEqual(sim.dsp_writes, [],
                         "指示がないのにDSPへ書き込んでしまっている")

    def _issue(self, sim, seq, reg, val, max_steps=200):
        """ホスト側の1回のDSP書き込み手順を再現し、ACKが返るまで回す。"""
        sim.host_to_spc[1] = reg     # $F5
        sim.host_to_spc[2] = val     # $F6
        sim.host_to_spc[0] = seq     # $F4 (最後に書く)
        for _ in range(max_steps):
            sim.step()
            if sim.spc_to_host[0] == seq:
                return True
        return False

    def test_driver_writes_single_dsp_register(self):
        sim = self._boot()
        self.assertTrue(self._issue(sim, 1, 0x6C, 0x20), "ACKが返ってこない")
        self.assertEqual(sim.dsp_writes, [(0x6C, 0x20)])
        self.assertEqual(sim.dsp[0x6C], 0x20)

    def test_driver_handles_a_full_key_on_sequence(self):
        """1音キーオンぶんのレジスタ列がすべて正しく届くこと。"""
        sim = self._boot()
        expected = [
            (0x5C, 0x01), (0x5C, 0x00),
            (0x04, 0x03), (0x05, 0xDF), (0x06, 0x6D),
            (0x02, 0x30), (0x03, 0x04),
            (0x00, 0x1B), (0x01, 0x1C),
            (0x4C, 0x01), (0x4C, 0x00),
        ]
        for i, (reg, val) in enumerate(expected, start=1):
            self.assertTrue(self._issue(sim, i & 0xFF, reg, val),
                            f"{i}件目({reg:02X}={val:02X})でACKが返らない")
        self.assertEqual(sim.dsp_writes, expected)

    def test_driver_sequence_wraps_around(self):
        """シーケンス値が256を跨いで一周しても取りこぼさないこと。"""
        sim = self._boot()
        seq = 0
        for i in range(300):
            seq = (seq + 1) & 0xFF
            reg = 0x10 | (i & 0x07)
            self.assertTrue(self._issue(sim, seq, reg, i & 0xFF),
                            f"{i}回目でACKが返らない (seq={seq})")
        self.assertEqual(len(sim.dsp_writes), 300)

    def test_driver_ignores_repeated_sequence(self):
        """同じシーケンス値を書き直しても二重に実行しないこと。"""
        sim = self._boot()
        self.assertTrue(self._issue(sim, 1, 0x0C, 0x7F))
        before = len(sim.dsp_writes)
        sim.host_to_spc[1] = 0x1C
        sim.host_to_spc[2] = 0x7F
        # $F4は1のまま(＝新しい指示ではない)
        for _ in range(300):
            sim.step()
        self.assertEqual(len(sim.dsp_writes), before,
                         "シーケンス値が変わっていないのに実行してしまった")

    def test_driver_code_size_fits_its_slot(self):
        self.assertLess(hardware.DRIVER_ADDR + len(hardware.DRIVER_CODE),
                        hardware.DIR_ADDR,
                        "ドライバがサンプルディレクトリ領域に食い込む")


# ============================================================================
# ARAMのメモリマップとサンプル配置
# ============================================================================

class TestSampleImage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = instruments.build_bank()

    def test_image_fits_in_aram(self):
        blob, directory, srcn = hardware.build_sample_image(self.bank)
        self.assertEqual(hardware.check_memory_map(len(blob), len(directory)), [])
        self.assertEqual(len(srcn), len(self.bank))
        self.assertEqual(len(directory), 4 * len(self.bank))

    def test_directory_points_at_real_samples(self):
        blob, directory, srcn = hardware.build_sample_image(self.bank)
        for name, index in srcn.items():
            entry = directory[index * 4:index * 4 + 4]
            start = entry[0] | (entry[1] << 8)
            offset = start - hardware.SAMPLE_ADDR
            self.assertGreaterEqual(offset, 0)
            self.assertLess(offset, len(blob))
            expected = self.bank[name].brr_data
            self.assertEqual(bytes(blob[offset:offset + len(expected)]), expected,
                             f"{name} のBRRデータがディレクトリの指す位置と食い違う")

    def test_directory_stays_inside_its_page(self):
        _, directory, _ = hardware.build_sample_image(self.bank)
        self.assertLessEqual(hardware.DIR_ADDR + len(directory), hardware.SAMPLE_ADDR)

    def test_oversized_bank_is_rejected(self):
        # $0400 + 0xFC00 = $10000 で、IPL ROMシャドウ($FFC0)どころかARAMの外
        problems = hardware.check_memory_map(0xFC00, 80)
        self.assertTrue(problems, "ARAMに収まらないサイズが検出されていない")

    def test_oversized_directory_is_rejected(self):
        # 1音色4バイトなので、音色を増やしすぎるとBRR領域に食い込む
        problems = hardware.check_memory_map(1000, 0x200)
        self.assertTrue(problems, "ディレクトリの食い込みが検出されていない")


# ============================================================================
# イベント列 → レジスタ書き込み → ストリームレコード
# ============================================================================

class TestRegisterConversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = instruments.build_bank()
        _, _, cls.srcn = hardware.build_sample_image(cls.bank)

    def test_key_on_emits_full_register_set(self):
        ev = engine.KeyOn(1.0, 3, "piano", 0x0430, 40, 50, 0xDF, 0x6D)
        writes = hardware.to_register_writes([ev], self.srcn)
        regs = {reg for _, reg, _ in writes}
        base = 3 << 4
        for offset, label in [(0, "VOLL"), (1, "VOLR"), (2, "PITCHL"),
                              (3, "PITCHH"), (4, "SRCN"), (5, "ADSR1"), (6, "ADSR2")]:
            self.assertIn(base + offset, regs, f"ボイス3の{label}が書かれていない")
        self.assertIn(hardware.DSP_KON, regs)
        self.assertIn(hardware.DSP_KOF, regs)

    def test_key_on_values_are_correct(self):
        ev = engine.KeyOn(0.0, 0, "piano", 0x1234, -20, 60, 0xDF, 0x6D)
        writes = hardware.to_register_writes([ev], self.srcn)
        table = {reg: val for _, reg, val in writes if reg < 0x10}
        self.assertEqual(table[0x02], 0x34, "PITCHの下位バイトが違う")
        self.assertEqual(table[0x03], 0x12, "PITCHの上位バイトが違う")
        self.assertEqual(table[0x04], self.srcn["piano"], "SRCNが違う")
        self.assertEqual(table[0x05], 0xDF)
        self.assertEqual(table[0x06], 0x6D)
        # 負の音量は符号付き8bitとして送る
        self.assertEqual(table[0x00], 0xEC, "VOLLの符号付き変換が違う")
        self.assertEqual(table[0x01], 60)

    def test_pitch_high_byte_is_masked_to_14bit(self):
        ev = engine.KeyOn(0.0, 0, "piano", 0x3FFF, 10, 10, 0xDF, 0x6D)
        writes = hardware.to_register_writes([ev], self.srcn)
        table = {reg: val for _, reg, val in writes if reg < 0x10}
        self.assertEqual(table[0x03], 0x3F, "PITCHの上位が14bitにマスクされていない")

    def test_key_on_orders_kof_before_kon(self):
        ev = engine.KeyOn(0.0, 0, "piano", 0x1000, 10, 10, 0xDF, 0x6D)
        writes = hardware.to_register_writes([ev], self.srcn)
        kof_time = min(t for t, reg, _ in writes if reg == hardware.DSP_KOF)
        kon_time = min(t for t, reg, _ in writes if reg == hardware.DSP_KON)
        srcn_time = min(t for t, reg, _ in writes if reg == 0x04)
        self.assertLess(kof_time, srcn_time, "キーオフより先に音色を設定している")
        self.assertLess(srcn_time, kon_time, "音色設定より先にキーオンしている")

    def test_kon_and_kof_are_cleared_again(self):
        ev = engine.KeyOn(0.0, 0, "piano", 0x1000, 10, 10, 0xDF, 0x6D)
        writes = hardware.to_register_writes([ev], self.srcn)
        kon = [(t, v) for t, reg, v in writes if reg == hardware.DSP_KON]
        self.assertEqual(kon[-1][1], 0x00, "KONが0に戻されていない")
        kof = [(t, v) for t, reg, v in writes if reg == hardware.DSP_KOF]
        self.assertEqual(kof[-1][1], 0x00, "KOFが0に戻されていない")

    def test_writes_are_time_ordered(self):
        events = [
            engine.KeyOn(0.5, 0, "piano", 0x1000, 10, 10, 0xDF, 0x6D),
            engine.KeyOn(0.1, 1, "bass", 0x0800, 10, 10, 0xFF, 0xAC),
            engine.KeyOff(0.9, 0),
        ]
        writes = hardware.to_register_writes(events, self.srcn)
        times = [t for t, _, _ in writes]
        self.assertEqual(times, sorted(times), "レジスタ書き込みが時刻順になっていない")

    def test_unknown_instrument_is_skipped(self):
        ev = engine.KeyOn(0.0, 0, "存在しない音色", 0x1000, 10, 10, 0xDF, 0x6D)
        self.assertEqual(hardware.to_register_writes([ev], self.srcn), [])


class TestStreamRecords(unittest.TestCase):
    def test_record_layout(self):
        writes = [(0.0, 0x6C, 0x20), (0.001, 0x0C, 0x7F)]
        records = hardware.to_stream_records(writes)
        self.assertEqual(len(records), 8)
        self.assertEqual(records[0:4], bytes([0x00, 0x00, 0x6C, 0x20]))
        # 1ms = 10ティック(100µs単位)
        self.assertEqual(records[4:8], bytes([0x0A, 0x00, 0x0C, 0x7F]))

    def test_deltas_are_relative_and_accumulate_correctly(self):
        writes = [(0.0, 1, 1), (0.05, 2, 2), (0.20, 3, 3)]
        records = hardware.to_stream_records(writes)
        deltas = [records[i] | (records[i + 1] << 8) for i in range(0, len(records), 4)]
        self.assertEqual(deltas, [0, 500, 1500])
        self.assertEqual(sum(deltas), 2000, "累積が元の時刻(2.0秒相当)と合わない")

    def test_long_gap_is_split_into_nop_records(self):
        writes = [(0.0, 1, 1), (20.0, 2, 2)]
        records = hardware.to_stream_records(writes)
        rows = [records[i:i + 4] for i in range(0, len(records), 4)]
        nops = [r for r in rows if r[2] == hardware.NOP_REG]
        self.assertTrue(nops, "6.5秒を超える間隔がNOPに分割されていない")
        total = sum(r[0] | (r[1] << 8) for r in rows)
        self.assertEqual(total, 200000, "分割後の合計待ち時間が20秒ぶんになっていない")

    def test_no_delta_exceeds_field_width(self):
        writes = [(0.0, 1, 1), (60.0, 2, 2)]
        records = hardware.to_stream_records(writes)
        for i in range(0, len(records), 4):
            delta = records[i] | (records[i + 1] << 8)
            self.assertLessEqual(delta, hardware.MAX_DELTA_TICKS)

    def test_end_marker_is_not_a_valid_record(self):
        """終端マーカーが通常のレコードと衝突しないこと。"""
        self.assertEqual(hardware.END_MARKER, bytes([0xFF, 0xFF, 0xFF, 0xFF]))
        # 通常レコードのレジスタ番号は0x00-0x7FかNOP(0xFF)。
        # NOPレコードは値を0で埋めているので4バイトすべて0xFFにはならない。
        writes = [(0.0, 1, 1), (30.0, 2, 2)]
        records = hardware.to_stream_records(writes)
        rows = [records[i:i + 4] for i in range(0, len(records), 4)]
        self.assertNotIn(hardware.END_MARKER, rows)

    def test_flow_control_window_fits_firmware_ring(self):
        """
        PCの先行送信量がファーム側リングバッファを超えないこと。

        超えるとArduinoのリングバッファが溢れてイベントを取りこぼす。
        FIRMWARE_EVENT_SLOTS は spc_realtime.ino の EVENT_SLOTS と
        揃えておくこと。
        """
        self.assertLessEqual(hardware.STREAM_CREDITS, hardware.FIRMWARE_EVENT_SLOTS)

    def test_flow_control_window_covers_a_full_chord(self):
        """
        8音同時のキーオン(1音11レコード = 88レコード)が、
        往復待ちを挟まずに送り切れる窓であること。狭いと和音の発音が滲む。
        """
        chord = [engine.KeyOn(0.0, v, "piano", 0x1000, 40, 40, 0xDF, 0x6D)
                 for v in range(engine.NUM_VOICES)]
        bank = instruments.build_bank()
        _, _, srcn = hardware.build_sample_image(bank)
        per_note = len(hardware.to_register_writes([chord[0]], srcn))
        self.assertGreaterEqual(hardware.STREAM_CREDITS * 2, per_note * 4,
                                "和音1つを送るのに往復待ちが何度も入る")


# ============================================================================
# 変換パイプライン全体
# ============================================================================

class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = instruments.build_bank()

    def test_full_midi_to_stream(self):
        """テスト用MIDIが最後までレコード列になること。"""
        midi_events, _ = smf.parse_midi("test.mid")
        events, stats = engine.convert(midi_events, self.bank)
        _, _, srcn = hardware.build_sample_image(self.bank)
        writes = hardware.to_register_writes(events, srcn)
        records = hardware.to_stream_records(writes)

        self.assertGreater(stats["notes"], 0)
        self.assertGreater(len(writes), stats["notes"] * 5,
                           "1ノートあたりのレジスタ書き込みが少なすぎる")
        self.assertEqual(len(records) % 4, 0)

        # ストリームの総時間が曲の長さと一致すること
        total_ticks = sum(records[i] | (records[i + 1] << 8)
                          for i in range(0, len(records), 4))
        seconds = total_ticks * hardware.TICK_US / 1e6
        self.assertAlmostEqual(seconds, max(t for t, _, _ in writes), delta=0.01)

    def test_voice_numbers_stay_in_range(self):
        midi_events, _ = smf.parse_midi("test.mid")
        events, _ = engine.convert(midi_events, self.bank)
        for ev in events:
            self.assertIn(ev.voice, range(engine.NUM_VOICES))

    def test_all_registers_are_valid_dsp_addresses(self):
        midi_events, _ = smf.parse_midi("test.mid")
        events, _ = engine.convert(midi_events, self.bank)
        _, _, srcn = hardware.build_sample_image(self.bank)
        for _, reg, val in hardware.to_register_writes(events, srcn):
            self.assertLessEqual(reg, 0x7F, f"DSPレジスタ番号が範囲外: ${reg:02X}")
            self.assertLessEqual(val, 0xFF)

    def test_initial_dsp_writes_disable_echo(self):
        writes = dict(hardware.initial_dsp_writes(0x03))
        self.assertEqual(writes[hardware.DSP_FLG] & 0x20, 0x20,
                         "FLGのエコー書き込み禁止ビットが立っていない"
                         "(BRRサンプルが上書きされる)")
        self.assertEqual(writes[hardware.DSP_EDL], 0x00)
        self.assertEqual(writes[hardware.DSP_DIR], 0x03)


# ============================================================================
# 既存部分(BRR / エンジン / レンダラ)の回帰テスト
# ============================================================================

class TestBrr(unittest.TestCase):
    def test_roundtrip_preserves_shape(self):
        pcm = np.sin(2 * np.pi * np.arange(64) / 32).astype(np.float64)
        decoded, loop = brr.decode(brr.encode(pcm, loop=True))
        self.assertEqual(len(decoded), 64)
        self.assertEqual(loop, 0)
        # 4bit ADPCMなので完全一致はしないが、相関は高いはず
        corr = np.corrcoef(pcm, decoded)[0, 1]
        self.assertGreater(corr, 0.95, f"BRR往復後の相関が低すぎる ({corr:.3f})")

    def test_block_size(self):
        pcm = np.zeros(32)
        self.assertEqual(len(brr.encode(pcm)), 2 * brr.BLOCK_BYTES)

    def test_end_flag_set_on_last_block(self):
        data = brr.encode(np.zeros(32), loop=True)
        self.assertEqual(data[0] & 0x01, 0, "先頭ブロックにendフラグが立っている")
        self.assertEqual(data[9] & 0x01, 1, "最終ブロックにendフラグが立っていない")
        self.assertEqual(data[9] & 0x02, 2, "最終ブロックにloopフラグが立っていない")


class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = instruments.build_bank()

    def test_pitch_register_matches_note(self):
        # ノート60 (261.63Hz) を素の周波数1000Hzのサンプルで鳴らす場合
        pitch = engine._pitch_register(engine.note_to_hz(60), 1000.0)
        self.assertAlmostEqual(pitch, round(4096 * 261.63 / 1000), delta=1)

    def test_pitch_register_is_clamped(self):
        self.assertLessEqual(engine._pitch_register(99999.0, 1000.0), engine.PITCH_MAX)
        self.assertGreaterEqual(engine._pitch_register(0.0001, 1000.0), 1)

    def test_voice_stealing_never_exceeds_eight(self):
        seq = engine.Sequencer(self.bank)
        for i in range(20):
            seq.note_on(i * 0.01, 0, 60 + i, 100)
        active = sum(1 for v in seq.voices if v.active)
        self.assertLessEqual(active, engine.NUM_VOICES)
        self.assertGreater(seq.stolen, 0, "8音を超えたのに音の奪い合いが起きていない")

    def test_sustain_pedal_holds_notes(self):
        seq = engine.Sequencer(self.bank)
        seq.control_change(0.0, 0, 64, 127)     # ペダルを踏む
        seq.note_on(0.1, 0, 60, 100)
        seq.note_off(0.2, 0, 60)
        self.assertTrue(any(v.active for v in seq.voices), "ペダル中に音が切れている")
        seq.control_change(0.3, 0, 64, 0)       # ペダルを離す
        self.assertFalse(any(v.active for v in seq.voices), "ペダルを離しても止まらない")

    def test_all_notes_off_stops_channel(self):
        seq = engine.Sequencer(self.bank)
        seq.note_on(0.0, 0, 60, 100)
        seq.note_on(0.0, 1, 64, 100)
        seq.control_change(0.5, 0, 123, 0)
        self.assertFalse(any(v.active and v.channel == 0 for v in seq.voices))
        self.assertTrue(any(v.active and v.channel == 1 for v in seq.voices),
                        "別チャンネルまで止めてしまっている")

    def test_drum_channel_uses_percussion(self):
        seq = engine.Sequencer(self.bank)
        seq.note_on(0.0, engine.DRUM_CHANNEL, 36, 100)
        keyons = [e for e in seq.events if isinstance(e, engine.KeyOn)]
        self.assertEqual(keyons[0].instrument, "kick")


class TestSmf(unittest.TestCase):
    def test_parses_test_file(self):
        events, info = smf.parse_midi("test.mid")
        self.assertGreater(len(events), 0)
        self.assertIn(info["format"], (0, 1))
        times = [e.time for e in events]
        self.assertEqual(times, sorted(times), "イベントが時刻順になっていない")

    def test_rejects_non_midi(self):
        with self.assertRaises(smf.MidiParseError):
            smf.parse_midi("test_midi2spc.py")


class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = instruments.build_bank()

    def test_render_produces_audio(self):
        events = [
            engine.KeyOn(0.0, 0, "piano", 0x0800, 100, 100, 0xDF, 0x6D),
            engine.KeyOff(0.5, 0),
        ]
        audio, peak = render.render(events, self.bank, tail=0.2)
        self.assertEqual(audio.shape[1], 2)
        self.assertGreater(peak, 0.0, "無音になっている")
        self.assertGreater(np.abs(audio).max(), 0.0)

    def test_silence_after_key_off(self):
        events = [
            engine.KeyOn(0.0, 0, "pluck", 0x0800, 100, 100, 0xDF, 0x6D),
            engine.KeyOff(0.2, 0),
        ]
        audio, _ = render.render(events, self.bank, tail=1.0)
        tail_region = audio[int(0.5 * render.SAMPLE_RATE):]
        self.assertLess(np.abs(tail_region).max(), 1e-3,
                        "キーオフ後に音が残っている")


if __name__ == "__main__":
    unittest.main(verbosity=2)
