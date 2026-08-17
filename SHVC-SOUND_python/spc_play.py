#!/usr/bin/env python3
"""
spc_play.py - .spcファイルをSHVC-SOUND(実チップ)で再生する

Arduino側は spc_uploader.ino (シリアルコマンド版) を書き込んでおくこと。

使い方:
    pip install pyserial
    python spc_play.py COM3 song.spc      (Windows)
    python spc_play.py /dev/ttyACM0 song.spc  (Linux)

.spcファイル形式(オフセットは既知の標準フォーマット):
    0x00-0x20 : ヘッダ("SNES-SPC700 Sound File Data v0.30" 等)
    0x25-0x26 : PC (リトルエンディアン)
    0x27      : A
    0x28      : X
    0x29      : Y
    0x2A      : PSW
    0x2B      : SP
    0x100-0x100FF : ARAM 64KB ダンプ
    0x10100-0x1017F : DSPレジスタ 128バイト
"""

import sys
import time
import serial

CMD_RESET = 0x01
CMD_SETADDR = 0x02
CMD_SENDBYTES = 0x03
CMD_READPORT = 0x04

ACK_RESET = 0x01
ACK_SETADDR = 0x02
ACK_CHUNK = 0x10
ACK_SENDBYTES = 0x03


class SpcFile:
    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < 0x10180:
            raise ValueError(".spcファイルとして小さすぎます(壊れているかも)")

        self.pc = data[0x25] | (data[0x26] << 8)
        self.a = data[0x27]
        self.x = data[0x28]
        self.y = data[0x29]
        self.psw = data[0x2A]
        self.sp = data[0x2B]

        self.ram = data[0x100:0x100 + 0x10000]           # 64KB
        self.dsp = data[0x10100:0x10100 + 0x80]           # 128バイト


class SpcController:
    def __init__(self, port, baud=115200):
        self.ser = serial.Serial(port, baud, timeout=10)
        time.sleep(2)  # Arduinoのリセット待ち(DTRでリセットがかかる環境向け)
        self.ser.reset_input_buffer()

    def _read_ack(self, expected):
        b = self.ser.read(1)
        if len(b) != 1 or b[0] != expected:
            raise RuntimeError(f"想定外の応答: {b!r} (期待値 0x{expected:02X})")

    def reset(self):
        print("SPC700をリセットしてready待ち...")
        self.ser.write(bytes([CMD_RESET]))
        self._read_ack(ACK_RESET)
        print("SPC700 ready.")

    def set_address(self, addr, continue_transfer):
        self.ser.write(bytes([CMD_SETADDR, addr & 0xFF, (addr >> 8) & 0xFF,
                               1 if continue_transfer else 0]))
        b = self.ser.read(1)
        if len(b) == 1 and b[0] == 0xEE:
            rest = self.ser.read(4)
            if len(rest) == 4 and rest[0] == 0xFF and rest[1] == 0xFF:
                raise RuntimeError(f"SETADDRがタイムアウト: addr=${addr:04X}")
            raise RuntimeError(f"SETADDR異常応答: {rest!r}")
        if len(b) != 1 or b[0] != ACK_SETADDR:
            raise RuntimeError(f"想定外の応答: {b!r} (期待値 0x{ACK_SETADDR:02X})")

    def send_bytes(self, data):
        length = len(data)
        self.ser.write(bytes([CMD_SENDBYTES, length & 0xFF, (length >> 8) & 0xFF]))

        diag = self.ser.read(3)
        if len(diag) != 3 or diag[0] != 0xAB:
            raise RuntimeError(f"len診断応答が異常: {diag!r} (送った長さ={length})")
        echoed_len = diag[1] | (diag[2] << 8)
        if echoed_len != length:
            raise RuntimeError(f"lenが化けた! 送った長さ={length}, Arduinoが受け取った長さ={echoed_len}")

        # Arduinoのシリアル受信バッファ(64バイト)を溢れさせないよう、
        # 16バイトずつ送って毎回ACKを待つ(きちんとしたフロー制御)
        CHUNK = 16
        pos = 0
        while pos < length:
            chunk_len = min(CHUNK, length - pos)
            self.ser.write(data[pos:pos + chunk_len])
            for _ in range(chunk_len):
                marker = self.ser.read(1)
                if len(marker) != 1:
                    raise RuntimeError(f"応答なし(タイムアウト)。進捗={pos}/{length}")
                if marker[0] == 0xEE:
                    rest = self.ser.read(4)
                    idx = rest[0] | (rest[1] << 8)
                    raise RuntimeError(
                        f"転送中にタイムアウト: バイト位置 {idx}/{length} で停止。"
                        f"送信した値=0x{rest[2]:02X}, 期待した応答=0x{idx & 0xFF:02X}, "
                        f"実際に読めた値=0x{rest[3]:02X}"
                    )
                if marker[0] != 0xCD:
                    raise RuntimeError(f"想定外の応答バイト: 0x{marker[0]:02X} (進捗={pos}/{length})")
                self.ser.read(1)  # インデックスの下位バイト(内容チェックは省略)
                pos += 1
            if pos % 320 == 0 or pos == length:
                print(f"    進捗: {pos}/{length} バイト転送済み")

        final = self.ser.read(1)
        if len(final) != 1 or final[0] != ACK_SENDBYTES:
            raise RuntimeError(f"最終応答が想定外: {final!r}")

    def write_block(self, addr, data):
        self.set_address(addr, True)
        self.send_bytes(data)

    def jump_to(self, addr):
        self.set_address(addr, False)

    def read_port(self, port):
        self.ser.write(bytes([CMD_READPORT, port]))
        resp = self.ser.read(2)
        if len(resp) != 2 or resp[0] != 0x04:
            raise RuntimeError(f"read_port応答が異常: {resp!r}")
        return resp[1]


def build_final_stub(spc: SpcFile, force_test_tone: bool = False) -> bytes:
    """
    DSPレジスタ128個・コントロール/タイマー・CPUレジスタをすべて復元して
    実行を開始する、SPC700側で実際に動くコード。

    メモリマップドI/O($F2/$F3等)への直接アドレス指定書き込みは信頼できない
    ことが実機で確認できたため、SPC700自身に「mov $F2,#idx / mov $F3,#val」を
    実行させる。このコードは高位アドレス($FFC0直下)に置く。

    ※既知の制限: スタブは約800バイトあり、$FFC0直下ということは
      $FC9x-$FFBF付近を占める。この領域はメインRAM転送($0100-$FFBF)の
      範囲内なので、曲データを800バイト分上書きしてしまう。
      この領域をサンプルデータやエコーバッファに使っている曲では
      ノイズや音の破綻が出る。要対策(スタブのループ化+テーブル参照で
      小型化する / エコーバッファ領域に置く 等)。

    最後に $00/$01 の実データを書き戻し、SP/PSW/A/X/Y を復元して
    本来のPCへジャンプする(Wikibooks "Loading SPC700 programs" の手法)。

    force_test_tone=True の場合、曲データ復元の直後に強制的にノイズテスト用の
    レジスタ上書きを追加する(診断用: 経路自体が生きているか確認するため)。
    """
    stub = bytearray()

    # 診断: スタブが実際に実行開始されたか確認するためのマーカー。
    # 実行されれば$F4(host側から見てport0)に0x99が現れるはず。
    stub += bytes([0x8F, 0x99, 0xF4])  # mov $F4,#0x99

    # DSPレジスタ128個を復元する。順序が重要:
    #  1. FLG($6C)にまず $20 を書く。soft reset(bit7)とmute(bit6)を解除しつつ、
    #     エコー書き込みは禁止(bit5=1)のままにする。ここで曲の保存値をそのまま
    #     書いてしまうと、ESA($6D)/EDL($7D)を設定する前にDSPがエコーデータを
    #     ARAMへ書き始め、転送済みの曲データを破壊する(特にEDL=0のときは
    #     エコーバッファ先頭4バイトを延々と上書きし続ける)。
    #  2. FLG/KON以外の126個を復元(この中でESA/EDLが正しい値になる)。
    #  3. KON($4C)を書いてキーオン。
    #  4. 最後にFLG($6C)へ保存値を書き、必要ならエコーを有効化する。
    stub += bytes([0x8F, 0x6C, 0xF2])
    stub += bytes([0x8F, 0x20, 0xF3])

    order = [i for i in range(0x80) if i not in (0x6C, 0x4C)] + [0x4C]
    for i in order:
        stub += bytes([0x8F, i, 0xF2])
        stub += bytes([0x8F, spc.dsp[i], 0xF3])

    stub += bytes([0x8F, 0x6C, 0xF2])
    stub += bytes([0x8F, spc.dsp[0x6C], 0xF3])

    # コントロールレジスタ・タイマー分周値を復元
    stub += bytes([0x8F, spc.ram[0xF1], 0xF1])
    stub += bytes([0x8F, spc.ram[0xFA], 0xFA])
    stub += bytes([0x8F, spc.ram[0xFB], 0xFB])
    stub += bytes([0x8F, spc.ram[0xFC], 0xFC])

    if force_test_tone:
        # 診断用: 以前成功したノイズテストと同じ強制上書き
        test_pokes = [
            (0x6C, 0x0A),  # FLG: mute=0,reset=0, ノイズクロック=0x0A
            (0x0C, 0x60),  # MVOLL
            (0x1C, 0x60),  # MVOLR
            (0x3D, 0x01),  # NON: ボイス0でノイズ有効
            (0x00, 0x7F),  # ボイス0 VOLL
            (0x01, 0x7F),  # ボイス0 VOLR
            (0x05, 0x00),  # ボイス0 ADSR1無効(GAIN直接モード)
            (0x07, 0x7F),  # ボイス0 GAIN最大
            (0x4C, 0x01),  # KON: ボイス0キーオン
        ]
        for idx, val in test_pokes:
            stub += bytes([0x8F, idx, 0xF2])
            stub += bytes([0x8F, val, 0xF3])
        # テストモードでは本来のCPUレジスタ復元・ジャンプはせず自己ループで停止
        stub += bytes([0x2F, 0xFE])  # BRA自己ループ
        return bytes(stub)

    # CPUレジスタ復元+ジャンプ
    # $00/$01 はメインRAM転送であえてスキップしている
    # (IPL ROMが転送中にこの2バイトを内部の転送先ポインタとして使うため)ので、
    # ここで実データを明示的に書き戻す。
    stub += bytes([0x8F, spc.ram[0x00], 0x00])   # mov $00,#byte0
    stub += bytes([0x8F, spc.ram[0x01], 0x01])   # mov $01,#byte1
    stub += bytes([0xCD, spc.sp])        # mov x,#sp
    stub += bytes([0xBD])                # mov sp,x
    stub += bytes([0xCD, spc.psw])       # mov x,#psw
    stub += bytes([0x4D])                # push x
    stub += bytes([0xE8, spc.a])         # mov a,#a
    stub += bytes([0xCD, spc.x])         # mov x,#x
    stub += bytes([0x8D, spc.y])         # mov y,#y
    stub += bytes([0x8E])                # pop psw
    stub += bytes([0x5F, spc.pc & 0xFF, (spc.pc >> 8) & 0xFF])  # jmp !abs pc

    return bytes(stub)


def play(port, spc_path, force_test_tone=False, skip_bulk=False, low_addr=False, only_stub=False):
    spc = SpcFile(spc_path)
    ctl = SpcController(port)

    ctl.reset()

    if not only_stub:
        # 1. メインRAMダンプを転送 ($F0-$FFは飛ばす。I/Oレジスタ領域で単純書き込み不可)
        # 重要: $0000/$0001 はIPL ROMが転送中に内部の転送先ポインタとして使うため、
        # 通常のデータ転送で書き込んではいけない。ここは$0002からにする。
        print("RAM $0002-$00EF 転送中...")
        ctl.write_block(0x0002, spc.ram[0x0002:0x00F0])

        if not skip_bulk:
            print("RAM $0100-$FFBF 転送中(数秒かかります)...")
            ctl.write_block(0x0100, spc.ram[0x0100:0xFFC0])
        else:
            print("(診断モード: RAM $0100-$FFBF 転送をスキップ)")
        # $FFC0-$FFFF (IPL ROMシャドウ領域) は転送不要
    else:
        print("(診断モード: スタブのみをリセット後最初の転送として送信)")

    # 2. DSPレジスタ・コントロール・タイマー・CPUレジスタをまとめて復元する
    #    実行コードを、曲データを壊さない高位アドレスに配置して実行する。
    print("復元スタブを構築・転送中...")
    stub = build_final_stub(spc, force_test_tone=force_test_tone)
    if low_addr:
        stub_addr = 0x0200
        print("  (診断モード: 低位アドレス$0200を使用)")
    else:
        stub_addr = 0xFFC0 - len(stub)
    print(f"  (スタブサイズ={len(stub)}バイト, 配置アドレス=${stub_addr:04X})")
    ctl.write_block(stub_addr, stub)

    print("実行開始...")
    ctl.jump_to(stub_addr)

    time.sleep(0.1)
    p0 = ctl.read_port(0)
    print(f"  (診断: 実行開始マーカー確認 port0=0x{p0:02X}, 期待値=0x99)")

    print("再生開始しました。")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"使い方: {sys.argv[0]} <シリアルポート> <spcファイル> [--test] [--skip-bulk] [--low-addr] [--only-stub]")
        sys.exit(1)
    flags = sys.argv[3:]
    test_mode = "--test" in flags
    skip_bulk_mode = "--skip-bulk" in flags
    low_addr_mode = "--low-addr" in flags
    only_stub_mode = "--only-stub" in flags
    play(sys.argv[1], sys.argv[2], force_test_tone=test_mode, skip_bulk=skip_bulk_mode,
         low_addr=low_addr_mode, only_stub=only_stub_mode)
