#!/usr/bin/env python3
"""
hardware.py - 実機(SHVC-SOUND)でリアルタイム演奏するためのバックエンド

render.py がPC上のS-DSPモデルに流していたイベント列を、
そのまま実チップのS-DSPレジスタ書き込みに変換して送りつける。

    engine.py のDSPイベント列
        │  to_register_writes()
        ▼
    (時刻, DSPレジスタ番号, 値) の列
        │  HardwarePlayer.play()
        ▼
    Arduino (spc_realtime.ino) → SPC700常駐ドライバ → S-DSP

■ 全体の段取り
  1. SPC700をリセットしてIPL ROMの転送モードに入る
  2. BRRサンプル・サンプルディレクトリ・常駐ドライバをARAMへ転送
  3. ドライバへジャンプ(以後SPC700はホストからの指示待ちループに入る)
  4. DSPの初期化(音量・エコー無効・DIR設定など)
  5. イベント列をArduinoへストリーム送信。実際の発音タイミングは
     Arduino側のリングバッファとタイマーが受け持つ

■ ARAMのメモリマップ
    $0200-$0216  常駐ドライバ(23バイト)
    $0300-$03FF  サンプルディレクトリ(1音色4バイト)
    $0400-       BRRサンプル本体(音色バンク全部でおよそ13KB)
"""

import time

from . import engine


# ---- ARAMのメモリマップ -----------------------------------------------------

DRIVER_ADDR = 0x0200
DIR_ADDR = 0x0300          # DIRレジスタは上位バイトのみ指定するので$xx00境界に置く
SAMPLE_ADDR = 0x0400

# ストリーム1目盛りの時間。イベントの時刻差はこの単位で送る。
TICK_US = 100
MAX_DELTA_TICKS = 0xFFFF   # 1レコードで表せる最大待ち時間 = 6.5535秒

NOP_REG = 0xFF             # 「DSPには書かず待つだけ」を表す擬似レジスタ番号
END_MARKER = bytes([0xFF, 0xFF, 0xFF, 0xFF])


# ---- SPC700常駐ドライバ -----------------------------------------------------
#
# ホストが $F5 にDSPレジスタ番号、$F6 に値を置いてから $F4 に
# 「前回と違う値」を書くと、それを検知してDSPへ書き込み、
# $F4 に同じ値を書き返してACKとする、というだけの23バイトのループ。
#
#   0200: 20        clrp            ; ダイレクトページを$00xxに固定
#   0201: CD 00     mov  x,#$00
#   0203: D8 F4     mov  $F4,x      ; ACKラッチを0に初期化
#   0205: 3E F4     cmp  x,$F4      ; loop: ホストからの新しい指示待ち
#   0207: F0 FC     beq  loop
#   0209: F8 F4     mov  x,$F4      ; 新しいシーケンス値
#   020B: E4 F5     mov  a,$F5      ; DSPレジスタ番号
#   020D: C4 F2     mov  $F2,a      ;   -> DSPADDR
#   020F: E4 F6     mov  a,$F6      ; 書き込む値
#   0211: C4 F3     mov  $F3,a      ;   -> DSPDATA
#   0213: D8 F4     mov  $F4,x      ; ACK(シーケンス値を返す)
#   0215: 2F EE     bra  loop
#
# 「曲をどう演奏するか」の判断はすべてPC側に残るので、SPC700側は
# これだけで足りる。音楽ドライバをアセンブリで書く必要はない。

DRIVER_CODE = bytes([
    0x20,
    0xCD, 0x00,
    0xD8, 0xF4,
    0x3E, 0xF4,
    0xF0, 0xFC,
    0xF8, 0xF4,
    0xE4, 0xF5,
    0xC4, 0xF2,
    0xE4, 0xF6,
    0xC4, 0xF3,
    0xD8, 0xF4,
    0x2F, 0xEE,
])


# ---- DSPレジスタ番号 --------------------------------------------------------

def voice_reg(voice, offset):
    """ボイス別レジスタ($x0-$x9, x=ボイス番号)の番号を求める。"""
    return (voice << 4) | offset


V_VOLL, V_VOLR, V_PITCHL, V_PITCHH, V_SRCN, V_ADSR1, V_ADSR2 = 0, 1, 2, 3, 4, 5, 6

DSP_MVOLL, DSP_MVOLR = 0x0C, 0x1C
DSP_EVOLL, DSP_EVOLR = 0x2C, 0x3C
DSP_KON, DSP_KOF = 0x4C, 0x5C
DSP_FLG, DSP_ENDX = 0x6C, 0x7C
DSP_EFB, DSP_PMON, DSP_NON, DSP_EON = 0x0D, 0x2D, 0x3D, 0x4D
DSP_DIR, DSP_ESA, DSP_EDL = 0x5D, 0x6D, 0x7D


# ---- サンプルバンク → ARAMイメージ -----------------------------------------

def build_sample_image(bank, base_addr=SAMPLE_ADDR):
    """
    音色バンクから、ARAMへ転送するBRR本体とサンプルディレクトリを作る。

    戻り値は (BRRデータ, ディレクトリデータ, {音色名: SRCN番号})。
    ディレクトリは1エントリ4バイト = [開始アドレスLE, ループ開始アドレスLE]。
    """
    blob = bytearray()
    directory = bytearray()
    srcn_map = {}

    for srcn, (name, inst) in enumerate(bank.items()):
        start = base_addr + len(blob)
        # ループなしの音色はループ位置を開始位置と同じにしておく
        # (endフラグで止まるのでループ位置は参照されない)
        loop = start
        blob += inst.brr_data
        directory += bytes([start & 0xFF, (start >> 8) & 0xFF,
                            loop & 0xFF, (loop >> 8) & 0xFF])
        srcn_map[name] = srcn

    return bytes(blob), bytes(directory), srcn_map


def check_memory_map(brr_len, dir_len):
    """ARAM(64KB)に収まるか、領域が重ならないかを確認する。"""
    problems = []
    if DIR_ADDR + dir_len > SAMPLE_ADDR:
        problems.append(
            f"サンプルディレクトリ({dir_len}バイト)が${SAMPLE_ADDR:04X}のBRR領域に食い込みます")
    if DRIVER_ADDR + len(DRIVER_CODE) > DIR_ADDR:
        problems.append("ドライバがディレクトリ領域に食い込みます")
    end = SAMPLE_ADDR + brr_len
    if end > 0xFFC0:
        problems.append(f"BRRデータの終端${end:04X}がARAMの上限を超えます")
    return problems


# ---- DSPの初期設定 ----------------------------------------------------------

def initial_dsp_writes(dir_page, master_volume=0x7F):
    """
    演奏開始前に一度だけ書くDSPレジスタ。

    エコーは使わない。FLGのbit5(エコー書き込み禁止)を立てておかないと、
    DSPがARAMへエコーデータを書き始めて転送済みのBRRサンプルを壊す。
    """
    writes = [
        (DSP_FLG, 0x20),            # ミュート解除・リセット解除・エコー書き込み禁止
        (DSP_KOF, 0xFF),            # 全ボイスをいったんキーオフ
        (DSP_KOF, 0x00),
        (DSP_KON, 0x00),
        (DSP_MVOLL, master_volume),
        (DSP_MVOLR, master_volume),
        (DSP_EVOLL, 0x00),          # エコー音量ゼロ
        (DSP_EVOLR, 0x00),
        (DSP_EFB, 0x00),
        (DSP_PMON, 0x00),           # ピッチモジュレーション未使用
        (DSP_NON, 0x00),            # ノイズ未使用
        (DSP_EON, 0x00),            # エコー送り未使用
        (DSP_DIR, dir_page),        # サンプルディレクトリの位置(上位バイト)
        (DSP_ESA, 0xFF),            # エコー未使用だが一応上端を指しておく
        (DSP_EDL, 0x00),
    ]
    # FIR係数8本($0F,$1F,...,$7F)もゼロにしておく
    for i in range(8):
        writes.append(((i << 4) | 0x0F, 0x00))
    # 各ボイスの音量もゼロから始める
    for v in range(engine.NUM_VOICES):
        writes.append((voice_reg(v, V_VOLL), 0x00))
        writes.append((voice_reg(v, V_VOLR), 0x00))
    return writes


# ---- DSPイベント列 → レジスタ書き込み列 ------------------------------------

def to_register_writes(events, srcn_map):
    """
    engine.py のDSPイベント列を (時刻秒, レジスタ番号, 値) の列に展開する。

    KON/KOFは「1のビットを書いた瞬間に効く」レジスタなので、
    立ててから少し後に0へ戻す(戻さないと次のキーオンで誤爆する)。
    """
    writes = []
    clear_delay = 0.0005  # KON/KOFを0に戻すまでの間隔(0.5ms)

    for ev in events:
        if isinstance(ev, engine.KeyOn):
            srcn = srcn_map.get(ev.instrument)
            if srcn is None:
                continue
            v = ev.voice
            bit = 1 << v
            t = ev.time
            # 同じボイスが鳴っていても確実に切ってから鳴らし直す
            writes.append((t, DSP_KOF, bit))
            writes.append((t + clear_delay, DSP_KOF, 0x00))
            t2 = t + clear_delay * 2
            writes.append((t2, voice_reg(v, V_SRCN), srcn))
            writes.append((t2, voice_reg(v, V_ADSR1), ev.adsr1))
            writes.append((t2, voice_reg(v, V_ADSR2), ev.adsr2))
            writes.append((t2, voice_reg(v, V_PITCHL), ev.pitch & 0xFF))
            writes.append((t2, voice_reg(v, V_PITCHH), (ev.pitch >> 8) & 0x3F))
            writes.append((t2, voice_reg(v, V_VOLL), ev.voll & 0xFF))
            writes.append((t2, voice_reg(v, V_VOLR), ev.volr & 0xFF))
            writes.append((t2 + clear_delay, DSP_KON, bit))
            writes.append((t2 + clear_delay * 2, DSP_KON, 0x00))

        elif isinstance(ev, engine.KeyOff):
            bit = 1 << ev.voice
            writes.append((ev.time, DSP_KOF, bit))
            writes.append((ev.time + clear_delay, DSP_KOF, 0x00))

        elif isinstance(ev, engine.SetPitch):
            v = ev.voice
            writes.append((ev.time, voice_reg(v, V_PITCHL), ev.pitch & 0xFF))
            writes.append((ev.time, voice_reg(v, V_PITCHH), (ev.pitch >> 8) & 0x3F))

        elif isinstance(ev, engine.SetVolume):
            v = ev.voice
            writes.append((ev.time, voice_reg(v, V_VOLL), ev.voll & 0xFF))
            writes.append((ev.time, voice_reg(v, V_VOLR), ev.volr & 0xFF))

    writes.sort(key=lambda w: w[0])
    return writes


def to_stream_records(writes):
    """
    (時刻, レジスタ, 値) の列を、Arduinoへ送る4バイトレコード列にする。

    レコード = [前のレコードからの待ち時間(100µs単位, LE16), レジスタ番号, 値]
    6.5秒を超える無音区間は、待つだけのNOPレコードに分割する。
    """
    records = bytearray()
    prev_ticks = 0

    for t, reg, val in writes:
        ticks = int(round(t * 1e6 / TICK_US))
        delta = max(0, ticks - prev_ticks)
        prev_ticks = ticks

        while delta > MAX_DELTA_TICKS:
            records += bytes([0xFF, 0xFF, NOP_REG, 0x00])
            delta -= MAX_DELTA_TICKS

        records += bytes([delta & 0xFF, (delta >> 8) & 0xFF, reg & 0xFF, val & 0xFF])

    return bytes(records)


# ---- 実機プレイヤー ---------------------------------------------------------

CMD_RESET = 0x01
CMD_DSPWRITE = 0x07
CMD_STREAM = 0x08
CMD_PANIC = 0x09
CMD_PING = 0x0A

ACK_RESET = 0x01
ACK_DSPWRITE = 0x07
ACK_STREAM_DONE = 0x08
ACK_PANIC = 0x09
CREDIT_BYTE = 0x5A
ERR_DRIVER_TIMEOUT = 0xE7

# PCが先行して送ってよいレコード数(フロー制御の窓)。
# リングバッファ段数を超えないこと(超えるとファーム側が取りこぼす)。
# 8音同時のキーオンは88レコードになるので、窓が狭いとそのたびに
# PCとの往復待ちが入って和音の発音が滲む。
STREAM_CREDITS = 48
FIRMWARE_EVENT_SLOTS = 96   # spc_realtime.ino の EVENT_SLOTS と一致させること

# ファームウェア識別(spc_realtime.ino の PING_MAGIC / FIRMWARE_VERSION)
PING_MAGIC = 0xA5
REQUIRED_FIRMWARE_VERSION = 1


class HardwarePlayer:
    """
    SHVC-SOUND実機でイベント列を演奏する。

    spc_play.SpcController を転送(IPLアップロード)に流用し、
    ドライバへジャンプしたあとは自前のコマンドで喋る。
    """

    def __init__(self, port, bank, log=None):
        # spc_play は同ディレクトリのモジュールなので遅延importする
        import spc_play

        self.log = log if log is not None else print
        self.bank = bank
        self.spc_play = spc_play
        self.ctl = spc_play.SpcController(port, log=self.log)
        self.srcn_map = {}
        self._seq = 0

    def close(self):
        self.ctl.close()

    # -- ファームウェアの確認 --
    def check_firmware(self):
        """
        Arduinoに spc_realtime.ino が載っているか確かめる。

        旧 spc_uploader.ino は知らないコマンドを黙って捨てる作りなので、
        PINGに無反応なら旧ファームだと判別できる。これを最初に確認しないと、
        転送だけ成功したあとに原因のわからないタイムアウトで止まる。
        """
        ser = self.ctl.ser
        ser.reset_input_buffer()
        original_timeout = ser.timeout
        ser.timeout = 1.0
        try:
            ser.write(bytes([CMD_PING]))
            resp = ser.read(2)
        finally:
            ser.timeout = original_timeout

        if len(resp) != 2 or resp[0] != PING_MAGIC:
            raise RuntimeError(
                "Arduinoのファームウェアがリアルタイム演奏に対応していません。\n"
                "spc_realtime.ino を書き込んでください "
                "(従来の spc_uploader.ino では .spc の転送しかできません)。\n"
                "  arduino-cli upload -p <ポート> --fqbn arduino:avr:nano spc_realtime")

        version = resp[1]
        if version != REQUIRED_FIRMWARE_VERSION:
            raise RuntimeError(
                f"ファームウェアのバージョンが違います "
                f"(Arduino側 v{version} / このソフトが想定しているのは "
                f"v{REQUIRED_FIRMWARE_VERSION})。spc_realtime.ino を書き込み直してください。")

        self.log(f"ファームウェア確認OK (spc_realtime v{version})")

    # -- 準備(ARAMへの転送とドライバ起動) --
    def upload(self, progress=None):
        blob, directory, srcn_map = build_sample_image(self.bank)
        self.srcn_map = srcn_map

        problems = check_memory_map(len(blob), len(directory))
        if problems:
            raise RuntimeError("ARAMのメモリマップに問題があります: " + " / ".join(problems))

        self.log(f"BRRサンプル {len(blob)}バイト({len(blob)/1024:.1f}KB) / "
                 f"ディレクトリ {len(directory)}バイト({len(srcn_map)}音色)")

        self.ctl.total_bytes = len(blob) + len(directory) + len(DRIVER_CODE)
        self.ctl.done_bytes = 0
        if progress is not None:
            self.ctl.on_progress = progress

        self.ctl.reset()

        self.log(f"サンプルディレクトリを${DIR_ADDR:04X}へ転送中...")
        self.ctl.write_block(DIR_ADDR, directory)
        self.ctl.done_bytes += len(directory)

        self.log(f"BRRサンプルを${SAMPLE_ADDR:04X}へ転送中...")
        self.ctl.write_block(SAMPLE_ADDR, blob)
        self.ctl.done_bytes += len(blob)

        self.log(f"常駐ドライバ({len(DRIVER_CODE)}バイト)を${DRIVER_ADDR:04X}へ転送中...")
        self.ctl.write_block(DRIVER_ADDR, DRIVER_CODE)
        self.ctl.done_bytes += len(DRIVER_CODE)

        self.log("ドライバへジャンプ...")
        self.ctl.jump_to(DRIVER_ADDR)
        time.sleep(0.05)

    # -- 単発のDSPレジスタ書き込み --
    def dsp_write(self, reg, val):
        self.ctl.ser.write(bytes([CMD_DSPWRITE, reg & 0xFF, val & 0xFF]))
        resp = self.ctl.ser.read(1)
        if len(resp) != 1:
            raise RuntimeError(
                "DSP書き込みにArduinoが応答しません。ファームウェアが "
                "spc_realtime.ino でない可能性があります"
                "(旧ファームは未知のコマンドを黙って捨てます)。")
        if resp[0] == ERR_DRIVER_TIMEOUT:
            raise RuntimeError(
                "SPC700の常駐ドライバが応答しません。"
                "ドライバへのジャンプに失敗している可能性があります。")
        if resp[0] != ACK_DSPWRITE:
            raise RuntimeError(f"DSP書き込みの応答が異常: 0x{resp[0]:02X}")

    def init_dsp(self, master_volume=0x7F):
        self.log("DSPを初期化中...")
        for reg, val in initial_dsp_writes(DIR_ADDR >> 8, master_volume):
            self.dsp_write(reg, val)

    # -- イベント列のストリーム再生 --
    def stream(self, records, progress=None, cancelled=None):
        """
        4バイトレコード列をArduinoへ流し込む。

        Arduinoは受け取ったレコードをリングバッファに積み、
        指定の待ち時間どおりにDSPへ書き込む。1レコード消化するごとに
        クレジットバイトを返してくるので、それを数えて送りすぎを防ぐ。
        """
        ser = self.ctl.ser
        total = len(records) // 4
        if total == 0:
            return

        ser.reset_input_buffer()
        ser.write(bytes([CMD_STREAM]))

        credits = STREAM_CREDITS
        sent = 0
        pos = 0

        while pos < len(records):
            if cancelled is not None and cancelled():
                self.log("再生の中止を要求されました。")
                break

            if credits <= 0:
                # バッファが埋まっている。クレジットが返るまで待つ。
                chunk = ser.read(1)
                if len(chunk) != 1:
                    raise RuntimeError(
                        f"Arduinoからの応答が途絶えました(送信済み {sent}/{total} レコード)")
                if chunk[0] == CREDIT_BYTE:
                    credits += 1
                elif chunk[0] == ERR_DRIVER_TIMEOUT:
                    raise RuntimeError("再生中にSPC700の常駐ドライバが応答しなくなりました。")
                else:
                    raise RuntimeError(f"想定外の応答バイト: 0x{chunk[0]:02X}")
                # 溜まっているクレジットをまとめて回収する
                waiting = ser.in_waiting
                if waiting:
                    extra = ser.read(waiting)
                    credits += extra.count(CREDIT_BYTE)
                continue

            # クレジットのぶんだけまとめて送る
            n = min(credits, (len(records) - pos) // 4)
            ser.write(records[pos:pos + n * 4])
            pos += n * 4
            credits -= n
            sent += n
            if progress is not None:
                progress(sent, total)

        ser.write(END_MARKER)

        # 残りのイベントが鳴り終わるまで、クレジットと完了応答を待つ。
        # まだ演奏中ならクレジットが返り続けるので、それを受け取るたびに
        # 待ち時間を延長する(長い無音区間で誤って見切らないため)。
        idle_limit = 15.0
        deadline = time.time() + idle_limit
        while time.time() < deadline:
            b = ser.read(1)
            if len(b) != 1:
                continue
            if b[0] == ACK_STREAM_DONE:
                self.log("ストリーム再生が完了しました。")
                return
            if b[0] == ERR_DRIVER_TIMEOUT:
                raise RuntimeError("再生中にSPC700の常駐ドライバが応答しなくなりました。")
            if b[0] == CREDIT_BYTE:
                deadline = time.time() + idle_limit
        self.log("完了応答を待てませんでした(再生自体は終わっている可能性があります)。")

    def silence(self):
        """全ボイスをキーオフして黙らせる。"""
        try:
            self.dsp_write(DSP_KOF, 0xFF)
            self.dsp_write(DSP_KOF, 0x00)
            self.dsp_write(DSP_MVOLL, 0x00)
            self.dsp_write(DSP_MVOLR, 0x00)
        except Exception as e:
            self.log(f"消音に失敗: {e}")


def play_on_hardware(port, events, bank, master_volume=0x7F,
                     log=None, progress=None, cancelled=None):
    """
    イベント列を実機で最初から最後まで演奏する(この関数はブロックする)。
    """
    log = log if log is not None else print
    player = HardwarePlayer(port, bank, log=log)
    try:
        # 転送を始める前にファームウェアを確認する。ここで弾いておかないと、
        # 転送だけ通ってから原因のわからないタイムアウトで止まることになる。
        player.check_firmware()
        player.upload(progress=progress)
        player.init_dsp(master_volume=master_volume)

        writes = to_register_writes(events, player.srcn_map)
        records = to_stream_records(writes)
        log(f"DSPレジスタ書き込み {len(writes)}回 "
            f"({len(records)}バイトのストリーム)を送信します。")

        player.stream(records, progress=progress, cancelled=cancelled)
        player.silence()
    finally:
        player.close()


def stop_hardware(port, log=None):
    """実機をリセットして音を止める。"""
    import spc_play
    log = log if log is not None else print
    spc_play.stop(port, log=log)
