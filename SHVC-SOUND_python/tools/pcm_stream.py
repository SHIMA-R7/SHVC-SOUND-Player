"""
録音をBRRに変換し、SHVC-SOUNDへ流し込みながら曲を最後まで鳴らす(案A: ストリーミング再生)。

仕組み
  ARAMの $0400-$FEFF をBRRのリングバッファにする。S-DSPのボイス0はこのバッファを
  頭から読み、最後のブロック(loop+endフラグ)でバッファ先頭へ戻ってループし続ける。
  PCは「S-DSPが今どこを読んでいるか」を経過時間から見積もり、その少し先まで
  データを書き足し続ける。書くのはSPC700上の常駐ドライバ(PCM_DRIVER)。

  PCM_DRIVER($0200) : ホストが$F4に新しいシーケンス値を書いたら、$F7のコマンドで分岐
    $F7=0 : DSPレジスタ書き込み ($F5=レジスタ, $F6=値)  … 従来の常駐ドライバと同じ
    $F7=1 : 1バイト書き込み ($F5)
    $F7=2 : 2バイト書き込み ($F5, $F6)
    書き込み先は $02-$03 のポインタ。1バイトごとに進め、$06-$07(終端)に来たら $04-$05(先頭)へ戻す。
    処理後に $F4 へシーケンス値を返してACKとする。

使い方(tools/.venv-transcribe の python で実行):
  python pcm_stream.py --selftest
  python pcm_stream.py 入力.wav [--rate 8000] [--start 0] [--seconds 60] [--port COM10]
"""
import argparse
import os
import sys
import time

import numpy as np

PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # SHVC-SOUND_python
sys.path.insert(0, PY_DIR)
from midi2spc import brr, hardware  # noqa: E402

DRIVER_ADDR = 0x0200
DIR_ADDR = 0x0300
RING_START = 0x0400
RING_BLOCKS = (0xFF00 - RING_START) // brr.BLOCK_BYTES
RING_END = RING_START + RING_BLOCKS * brr.BLOCK_BYTES      # この番地は含まない

def assemble(org, program):
    """
    命令を (ラベル or None, 命令バイト列, 分岐先ラベル, 分岐の種類) で並べた最小限のアセンブラ。
    分岐の種類: 'rel' = 相対分岐(最後の1バイト) / 'abs' = 絶対番地(最後の2バイト)
    """
    addr, labels, sized = org, {}, []
    for label, code, target, kind in program:
        if label:
            labels[label] = addr
        sized.append((addr, code, target, kind))
        addr += len(code) + (1 if kind == "rel" else 2 if kind == "abs" else 0)
    out = bytearray()
    for addr, code, target, kind in sized:
        out += code
        if kind == "rel":
            off = labels[target] - (addr + len(code) + 1)
            assert -128 <= off <= 127, f"分岐が届かない: {target}"
            out.append(off & 0xFF)
        elif kind == "abs":
            out += bytes([labels[target] & 0xFF, labels[target] >> 8])
    return bytes(out), labels


def _(label, *code, to=None, kind=None):
    return (label, bytes(code), to, kind)


PCM_DRIVER, DRIVER_LABELS = assemble(DRIVER_ADDR, [
    _(None, 0x20),                          # clrp
    _(None, 0xCD, 0x00),                    # mov x,#0
    _(None, 0xD8, 0xF4),                    # mov $F4,x
    _("loop", 0x3E, 0xF4),                  # cmp x,$F4
    _(None, 0xF0, to="loop", kind="rel"),   # beq loop
    _(None, 0xF8, 0xF4),                    # mov x,$F4       ; シーケンス値
    _(None, 0xE4, 0xF7),                    # mov a,$F7       ; コマンド
    _(None, 0xF0, to="dsp", kind="rel"),    # beq dsp         ; 0
    _(None, 0x68, 0x01),                    # cmp a,#1
    _(None, 0xF0, to="wr1", kind="rel"),
    _(None, 0x68, 0x02),                    # cmp a,#2
    _(None, 0xF0, to="wr2", kind="rel"),
    _(None, 0x68, 0x03),                    # cmp a,#3
    _(None, 0xF0, to="info", kind="rel"),
    _(None, 0x68, 0x04),                    # cmp a,#4
    _(None, 0xF0, to="dread", kind="rel"),
    _(None, 0x68, 0x05),                    # cmp a,#5
    _(None, 0xF0, to="setptr", kind="rel"),
    _(None, 0x68, 0x06),                    # cmp a,#6
    _(None, 0xF0, to="peek", kind="rel"),
    _(None, 0x2F, to="ack", kind="rel"),    # 知らないコマンドは何もせずACK
    # 6: [$02-$03]の1バイトをホストから見た$F5に返し、ポインタを1進める(折り返さない。読み返し検査用)
    _("peek", 0x8D, 0x00),                  # mov y,#0
    _(None, 0xF7, 0x02),                    # mov a,[$02]+y
    _(None, 0xC4, 0xF5),                    # mov $F5,a
    _(None, 0x3A, 0x02),                    # incw $02
    _(None, 0x2F, to="ack", kind="rel"),
    # 5: 書き込みポインタを設定 ($F5=下位, $F6=上位)
    #    起動直後、IPLのジャンプで残ったポート値を指示と誤認して1回書いてしまうので、
    #    ホストは起動後にこれで正しい位置へ合わせ直す
    _("setptr", 0xE4, 0xF5), _(None, 0xC4, 0x02), _(None, 0xE4, 0xF6), _(None, 0xC4, 0x03),
    _(None, 0x2F, to="ack", kind="rel"),
    # 0: DSPレジスタ書き込み ($F5=レジスタ, $F6=値)
    _("dsp", 0xE4, 0xF5), _(None, 0xC4, 0xF2), _(None, 0xE4, 0xF6), _(None, 0xC4, 0xF3),
    _(None, 0x2F, to="ack", kind="rel"),
    # 4: DSPレジスタ読み出し ($F5=レジスタ) → ホストから見た$F5に値
    _("dread", 0xE4, 0xF5), _(None, 0xC4, 0xF2), _(None, 0xE4, 0xF3), _(None, 0xC4, 0xF5),
    _(None, 0x2F, to="ack", kind="rel"),
    # 3: 書き込みポインタを返す → ホストから見た$F5/$F6
    _("info", 0xE4, 0x02), _(None, 0xC4, 0xF5), _(None, 0xE4, 0x03), _(None, 0xC4, 0xF6),
    _(None, 0x2F, to="ack", kind="rel"),
    # 2: 2バイト書き込み
    _("wr2", 0xE4, 0xF5), _(None, 0x3F, to="put", kind="abs"),
    _(None, 0xE4, 0xF6), _(None, 0x3F, to="put", kind="abs"),
    _(None, 0x2F, to="ack", kind="rel"),
    # 1: 1バイト書き込み
    _("wr1", 0xE4, 0xF5), _(None, 0x3F, to="put", kind="abs"),
    _("ack", 0xD8, 0xF4),                   # mov $F4,x       ; ACK
    _(None, 0x2F, to="loop", kind="rel"),
    # put: Aを[$02-$03]へ書き、ポインタを進める。終端($06-$07)で先頭($04-$05)へ戻す
    _("put", 0x8D, 0x00),                   # mov y,#0
    _(None, 0xD7, 0x02),                    # mov [$02]+y,a
    _(None, 0x3A, 0x02),                    # incw $02
    _(None, 0xBA, 0x02),                    # movw ya,$02
    _(None, 0x5A, 0x06),                    # cmpw ya,$06
    _(None, 0xD0, to="ret", kind="rel"),    # bne ret
    _(None, 0xBA, 0x04),                    # movw ya,$04
    _(None, 0xDA, 0x02),                    # movw $02,ya
    _("ret", 0x6F),                         # ret
])
assert DRIVER_ADDR + len(PCM_DRIVER) <= DIR_ADDR

CMD_DSPWRITE, ACK_DSPWRITE = 0x07, 0x07
CMD_PCMCHUNK, ACK_PCMCHUNK = 0x0C, 0x0C
CMD_DRVQUERY = 0x0D
CMD_DRVPEEK = 0x0E
ERR_DRIVER_TIMEOUT = 0xE7


# ---- 自己テスト用のSPC700簡易シミュレータ ------------------------------------

class Sim:
    def __init__(self):
        self.ram = bytearray(0x10000)
        self.ram[DRIVER_ADDR:DRIVER_ADDR + len(PCM_DRIVER)] = PCM_DRIVER
        self.pc, self.a, self.x, self.y, self.sp = DRIVER_ADDR, 0, 0, 0, 0xEF
        self.z = self.n = False
        self.host_in = [0, 0, 0, 0]     # ホスト→SPC700 ($F4-$F7 を読むと見える値)
        self.out = [0, 0, 0, 0]         # SPC700→ホスト
        self.dsp = {}
        self.dsp_addr = 0

    def rd(self, a):
        if 0xF4 <= a <= 0xF7:
            return self.host_in[a - 0xF4]
        if a == 0xF3:
            return self.dsp.get(self.dsp_addr, 0)
        return self.ram[a]

    def wr(self, a, v):
        if 0xF4 <= a <= 0xF7:
            self.out[a - 0xF4] = v
        elif a == 0xF2:
            self.dsp_addr = v
        elif a == 0xF3:
            self.dsp[self.dsp_addr] = v
        else:
            self.ram[a] = v

    def f(self):
        v = self.ram[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def nz(self, v, bits=8):
        self.z = v == 0
        self.n = bool(v >> (bits - 1) & 1)

    def rel(self, cond):
        r = self.f()
        if cond:
            self.pc = (self.pc + (r - 256 if r >= 128 else r)) & 0xFFFF

    def step(self):
        op = self.f()
        if op == 0x20:
            pass
        elif op == 0xCD:
            self.x = self.f(); self.nz(self.x)
        elif op == 0x8D:
            self.y = self.f(); self.nz(self.y)
        elif op == 0xD8:
            self.wr(self.f(), self.x)
        elif op == 0xC4:
            self.wr(self.f(), self.a)
        elif op == 0x3E:
            v = self.rd(self.f()); self.nz((self.x - v) & 0xFF)
        elif op == 0x68:
            v = self.f(); self.nz((self.a - v) & 0xFF)
        elif op == 0xF8:
            self.x = self.rd(self.f()); self.nz(self.x)
        elif op == 0xE4:
            self.a = self.rd(self.f()); self.nz(self.a)
        elif op == 0xF0:
            self.rel(self.z)
        elif op == 0xD0:
            self.rel(not self.z)
        elif op == 0x2F:
            self.rel(True)
        elif op == 0x3F:
            lo, hi = self.f(), self.f()
            ret = self.pc
            self.ram[0x100 + self.sp] = ret >> 8; self.sp -= 1
            self.ram[0x100 + self.sp] = ret & 0xFF; self.sp -= 1
            self.pc = lo | hi << 8
        elif op == 0x6F:
            self.sp += 1; lo = self.ram[0x100 + self.sp]
            self.sp += 1; hi = self.ram[0x100 + self.sp]
            self.pc = lo | hi << 8
        elif op == 0xF7:
            d = self.f()
            ptr = self.ram[d] | self.ram[(d + 1) & 0xFF] << 8
            self.a = self.rd((ptr + self.y) & 0xFFFF); self.nz(self.a)
        elif op == 0xD7:
            d = self.f()
            ptr = self.ram[d] | self.ram[(d + 1) & 0xFF] << 8
            self.wr((ptr + self.y) & 0xFFFF, self.a)
        elif op == 0x3A:
            d = self.f()
            w = (self.ram[d] | self.ram[d + 1] << 8) + 1 & 0xFFFF
            self.ram[d], self.ram[d + 1] = w & 0xFF, w >> 8
            self.nz(w, 16)
        elif op == 0xBA:
            d = self.f()
            self.a, self.y = self.ram[d], self.ram[d + 1]
            self.nz(self.a | self.y << 8, 16)
        elif op == 0xDA:
            d = self.f()
            self.ram[d], self.ram[d + 1] = self.a, self.y
        elif op == 0x5A:
            d = self.f()
            w = self.ram[d] | self.ram[d + 1] << 8
            self.nz(((self.a | self.y << 8) - w) & 0xFFFF, 16)
        else:
            raise AssertionError(f"未対応命令 {op:02X} at {self.pc - 1:04X}")

    def host_command(self, cmd, b1=0, b2=0, max_steps=200):
        seq = (self.host_in[0] + 1) & 0xFF
        self.host_in[1], self.host_in[2], self.host_in[3] = b1, b2, cmd
        self.host_in[0] = seq
        for _ in range(max_steps):
            self.step()
            if self.out[0] == seq and self.pc == DRIVER_LABELS["loop"]:
                return True
        return False


def selftest():
    s = Sim()
    start, end = 0x0400, 0x0400 + 9
    s.ram[2:8] = bytes([start & 0xFF, start >> 8, start & 0xFF, start >> 8, end & 0xFF, end >> 8])
    for _ in range(3):
        s.step()
    assert s.out[0] == 0, "起動時にACKラッチが0にならない"
    assert s.host_command(0, 0x4C, 0x01) and s.dsp == {0x4C: 0x01}, "DSP書き込みが通らない"
    data = list(range(1, 14))                      # 13バイト書く → 9バイトで先頭に戻って4バイト上書き
    i = 0
    while i < len(data):
        if len(data) - i >= 2:
            assert s.host_command(2, data[i], data[i + 1]), "2バイト書き込みでACKが来ない"
            i += 2
        else:
            assert s.host_command(1, data[i]), "1バイト書き込みでACKが来ない"
            i += 1
    got = list(s.ram[start:end])
    assert got == [10, 11, 12, 13, 5, 6, 7, 8, 9], f"リングバッファの中身が違う: {got}"
    ptr = s.ram[2] | s.ram[3] << 8
    assert ptr == start + 4, f"書き込みポインタが違う: {ptr:04X}"
    assert s.ram[end] == 0, "終端を越えて書いている"
    assert s.sp == 0xEF, "スタックがずれている"
    assert s.host_command(3) and (s.out[1] | s.out[2] << 8) == start + 4, "ポインタ問い合わせが違う"
    s.dsp[0x08] = 0x5A
    assert s.host_command(4, 0x08) and s.out[1] == 0x5A, "DSP読み出しが違う"
    assert s.host_command(5, 0x02, 0x04) and (s.ram[2] | s.ram[3] << 8) == 0x0402, "ポインタ設定が違う"
    # 起動直後に残っていたポート値(ジャンプ指示の名残)を誤認しても、設定し直せば正しい位置に書ける
    s2 = Sim()
    s2.ram[2:8] = bytes([0x00, 0x04, 0x00, 0x04, 0x00, 0x05])
    s2.host_in = [0x37, 0x00, 0x00, 0x02]           # IPLジャンプ後: port0=キック値, port3=番地の上位
    for _ in range(40):
        s2.step()
    assert (s2.ram[2] | s2.ram[3] << 8) == 0x0402, "起動直後の誤認書き込みが再現しない(想定と違う)"
    assert s2.host_command(5, 0x00, 0x04) and (s2.ram[2] | s2.ram[3] << 8) == 0x0400, "合わせ直しできない"
    s2.ram[0x0400:0x0403] = bytes([0xA1, 0xB2, 0xC3])
    got = []
    for _ in range(3):
        assert s2.host_command(6)
        got.append(s2.out[1])
    assert got == [0xA1, 0xB2, 0xC3] and (s2.ram[2] | s2.ram[3] << 8) == 0x0403, f"読み返しが違う: {got}"
    print(f"自己テストOK (ドライバ{len(PCM_DRIVER)}バイト / リング{RING_BLOCKS}ブロック "
          f"${RING_START:04X}-${RING_END - 1:04X})")


# ---- 実機ストリーミング -----------------------------------------------------

# S-DSPはBRRの復号値を15bit(±16383)で扱い、超えると飽和せず折り返す。
# brr.py の復号モデルは16bit相当で飽和させているので、PCでは問題なく聞こえても
# 実機では予測が崩れて音が壊れる。録音はこの割合までに収めてから変換する。
PCM_PEAK = 0.4


def encode_filter0(y):
    """
    予測を使わない(filter 0だけの)BRRにする。numpyでまとめて計算するので速い。

    実機の復号: s = (n << range) >> 1 を16bitで飽和 → 15bitで折り返し。
    各ブロックは前のブロックに依存しないので、PCと実機で予測の丸めがずれて
    長時間のうちに壊れていく、ということが起きない。
    """
    n = len(y) - len(y) % brr.BLOCK_SAMPLES
    t = np.round(np.clip(y[:n], -1, 1) * 16383).astype(np.int64).reshape(-1, brr.BLOCK_SAMPLES)
    best_err = None
    best_nib = best_rng = None
    for rng in range(13):
        if rng == 0:
            nib = np.clip(t * 2, -8, 7)
            dec = nib >> 1
        else:
            step = 1 << (rng - 1)
            nib = np.clip(np.round(t / step), -8, 7).astype(np.int64)
            dec = nib * step
        err = ((dec - t) ** 2).sum(axis=1)
        if best_err is None:
            best_err, best_nib, best_rng = err, nib, np.zeros(len(t), dtype=np.int64)
        else:
            better = err < best_err
            best_err = np.where(better, err, best_err)
            best_nib = np.where(better[:, None], nib, best_nib)
            best_rng = np.where(better, rng, best_rng)
    out = np.zeros((len(t), brr.BLOCK_BYTES), dtype=np.uint8)
    out[:, 0] = (best_rng << 4).astype(np.uint8)
    nibs = (best_nib & 0x0F).astype(np.uint8)
    out[:, 1:] = (nibs[:, 0::2] << 4) | nibs[:, 1::2]
    return out.tobytes()


def encode_song(wav, rate, start, seconds, cache, filter0=False, peak=None):
    import librosa
    if cache and os.path.exists(cache):
        data = np.fromfile(cache, dtype=np.uint8).tobytes()
        print(f"変換済みのBRRを使います: {cache} ({len(data) / 1024:.0f}KB)")
        return data
    y, _ = librosa.load(wav, sr=rate, mono=True, offset=start, duration=seconds)
    y = y / (np.max(np.abs(y)) + 1e-9) * (peak if peak is not None else PCM_PEAK)
    t = time.time()
    if filter0:
        print(f"{rate}Hz / {len(y) / rate:.1f}秒 をBRR(予測なし)に変換中...", flush=True)
        data = encode_filter0(y)
    else:
        print(f"{rate}Hz / {len(y) / rate:.1f}秒 をBRRに変換中(時間がかかります)...", flush=True)
        data = brr.encode(y, loop=False)
    print(f"  BRR {len(data) / 1024:.0f}KB ({time.time() - t:.0f}秒)", flush=True)
    if cache:
        np.frombuffer(data, dtype=np.uint8).tofile(cache)
    return data


def ring_flags(data):
    """ブロックのヘッダに、リング最後尾の位置だけ loop+end を立て、ほかは落とす。"""
    out = bytearray(data)
    for j in range(len(out) // brr.BLOCK_BYTES):
        h = j * brr.BLOCK_BYTES
        out[h] &= 0xFC
        if j % RING_BLOCKS == RING_BLOCKS - 1:
            out[h] |= 0x03
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", nargs="?")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rate", type=int, default=8000)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--volume", type=int, default=110, help="ボイス0の音量 VOLL/VOLR (0-127)")
    ap.add_argument("--master", type=int, default=0x7F, help="マスター音量 MVOLL/MVOLR (0-127)")
    ap.add_argument("--lead", type=float, default=4.0, help="再生位置より何秒先まで書いておくか")
    ap.add_argument("--chunk", type=int, default=254, help="1回にArduinoへ送るバイト数(偶数)")
    ap.add_argument("--ring-seconds", type=float, default=None,
                    help="リングバッファを何秒ぶんに縮めるか(折り返しの不具合を切り分ける診断用)")
    ap.add_argument("--filter0", action="store_true",
                    help="予測を使わないBRRにする(実機と予測がずれない。変換も速い)")
    ap.add_argument("--peak", type=float, default=None, help="録音を正規化するときの最大値(0-1)")
    ap.add_argument("--loop-whole", action="store_true",
                    help="音声全体をARAMに入れ、S-DSPだけでループ再生する(PCからの転送は不要)")
    ap.add_argument("--verify", action="store_true",
                    help="診断用: リング1周ぶんをIPLで入れたあと、ARAMを2回読み返して送ったデータと比べる")
    ap.add_argument("--static-loop", type=float, default=None, metavar="秒",
                    help="診断用: リング1周ぶんだけ先に入れて、転送なしでこの秒数ループ再生する")
    ap.add_argument("--wrap-timing", action="store_true",
                    help="S-DSPが実際にリング末尾を通過した時刻(ENDX)を測り、推定とのずれを表示する")
    ap.add_argument("--diag", action="store_true",
                    help="0.5秒ごとにSPC700側の書き込みポインタとボイス0の状態を表示する")
    args = ap.parse_args()

    selftest()
    if args.selftest:
        return 0
    if not args.wav:
        ap.error("入力WAVを指定してください")
    global RING_BLOCKS, RING_END
    if args.ring_seconds:
        want = int(args.ring_seconds * args.rate / brr.BLOCK_SAMPLES)
        RING_BLOCKS = max(64, min(RING_BLOCKS, want))
        RING_END = RING_START + RING_BLOCKS * brr.BLOCK_BYTES

    peak = args.peak if args.peak is not None else PCM_PEAK
    tag = (f"{os.path.splitext(args.wav)[0]}_{args.rate}hz_{args.start:g}_{args.seconds or 'all'}"
           f"_peak{peak:g}{'_f0' if args.filter0 else ''}.brr")
    raw = encode_song(args.wav, args.rate, args.start, args.seconds, tag,
                      filter0=args.filter0, peak=peak)
    if args.loop_whole:
        # 音声全体をちょうど1周にして、S-DSPだけで永遠にループさせる
        whole = len(raw) // brr.BLOCK_BYTES
        max_blocks = (0xFF00 - RING_START) // brr.BLOCK_BYTES
        if whole > max_blocks:
            raise SystemExit(f"音声が長すぎます({whole * brr.BLOCK_SAMPLES / args.rate:.1f}秒)。"
                             f"{args.rate}Hzでは{max_blocks * brr.BLOCK_SAMPLES / args.rate:.1f}秒までです")
        RING_BLOCKS = whole
        RING_END = RING_START + RING_BLOCKS * brr.BLOCK_BYTES
        if args.static_loop is None:
            args.static_loop = 3600.0
    data = ring_flags(raw)
    blocks = len(data) // brr.BLOCK_BYTES
    bps = args.rate * brr.BLOCK_BYTES / brr.BLOCK_SAMPLES        # S-DSPが1秒に読むバイト数
    ring_bytes = RING_BLOCKS * brr.BLOCK_BYTES
    max_lead_bytes = int(ring_bytes * 0.8)
    lead_bytes = min(int(args.lead * bps), max_lead_bytes)
    silence = bytearray()
    for j in range(blocks, blocks + int(bps * 0.5 / brr.BLOCK_BYTES) + 1):
        silence += bytes([0x03 if j % RING_BLOCKS == RING_BLOCKS - 1 else 0x00]) + bytes(8)
    data += bytes(silence)
    total = len(data)
    print(f"曲 {blocks * brr.BLOCK_SAMPLES / args.rate:.1f}秒 / S-DSPは毎秒{bps / 1024:.1f}KB読む / "
          f"リング{ring_bytes / 1024:.1f}KB({ring_bytes / bps:.1f}秒ぶん) / 先行{lead_bytes / bps:.1f}秒")

    from spc_play import SpcController
    ctl = SpcController(args.port, log=print)
    ser = ctl.ser

    def dsp(reg, val):
        ser.write(bytes([CMD_DSPWRITE, reg & 0xFF, val & 0xFF]))
        r = ser.read(1)
        if r != bytes([ACK_DSPWRITE]):
            raise RuntimeError(f"DSP書き込み失敗 reg=${reg:02X} 応答={r!r}")

    def query(cmd, arg=0, arg2=0):
        ser.write(bytes([CMD_DRVQUERY, cmd, arg, arg2]))
        r = ser.read(3)
        if len(r) != 3 or r[0] != CMD_DRVQUERY:
            raise RuntimeError(f"ドライバ問い合わせ失敗 cmd={cmd} 応答={r!r}")
        return r[1], r[2]

    def diag_line(elapsed):
        lo, hi = query(3)
        ptr = lo | hi << 8
        expect = RING_START + sent % ring_bytes
        envx, _ = query(4, 0x08)
        outx, _ = query(4, 0x09)
        endx, _ = query(4, 0x7C)
        mvol, _ = query(4, 0x0C)
        vol0, _ = query(4, 0x00)
        flg, _ = query(4, 0x6C)
        read_pos = RING_START + int(elapsed * bps) % ring_bytes
        print(f"  [診断] {elapsed:5.2f}秒 ポインタ${ptr:04X}(期待${expect:04X}) "
              f"推定読み位置${read_pos:04X} ENVX={envx:3d} OUTX={outx - 256 if outx > 127 else outx:4d} "
              f"ENDX={endx:08b} MVOL={mvol} VOL0={vol0} FLG=${flg:02X}", flush=True)

    sent = 0

    def send_chunk(n):
        nonlocal sent
        chunk = data[sent:sent + n]
        ser.write(bytes([CMD_PCMCHUNK, len(chunk)]) + chunk)
        r = ser.read(1)
        if r != bytes([ACK_PCMCHUNK]):
            raise RuntimeError(f"PCM転送失敗 (送信済み{sent}バイト) 応答={r!r}")
        sent += len(chunk)

    with hardware._keep_awake():
        try:
            ctl.reset()
            ctl.write_block(DIR_ADDR, bytes([RING_START & 0xFF, RING_START >> 8,
                                             RING_START & 0xFF, RING_START >> 8]))
            # 先行分はIPLの一括転送で先に入れておく(速い)
            full_ring = args.static_loop is not None or args.verify
            pre = min(total, ring_bytes if full_ring else lead_bytes)
            pre -= pre % brr.BLOCK_BYTES
            print(f"先行{pre / bps:.1f}秒ぶん({pre}バイト)をIPLで転送中...", flush=True)
            ctl.write_block(RING_START, data[:pre])
            ptr = RING_START + pre
            if ptr >= RING_END:
                ptr = RING_START
            ctl.write_block(0x0002, bytes([ptr & 0xFF, ptr >> 8, RING_START & 0xFF, RING_START >> 8,
                                           RING_END & 0xFF, RING_END >> 8]))
            ctl.write_block(DRIVER_ADDR, PCM_DRIVER)
            ctl.jump_to(DRIVER_ADDR)
            time.sleep(0.05)
            sent = pre
            # 起動直後の誤認書き込みでずれたポインタを、正しい位置に合わせ直す
            query(5, ptr & 0xFF, ptr >> 8)
            lo, hi = query(3)
            if (lo | hi << 8) != ptr:
                raise RuntimeError(f"書き込みポインタを合わせられません ${lo | hi << 8:04X} != ${ptr:04X}")

            if args.verify:
                def dump(n):
                    query(5, RING_START & 0xFF, RING_START >> 8)
                    out = bytearray()
                    t = time.time()
                    while len(out) < n:
                        k = min(255, n - len(out))
                        ser.write(bytes([CMD_DRVPEEK, k]))
                        head = ser.read(1)
                        if head != bytes([CMD_DRVPEEK]):
                            raise RuntimeError(f"読み返し失敗 {len(out)}バイト目 応答={head!r}")
                        out += ser.read(k)
                    print(f"  {n}バイト読み返し ({time.time() - t:.1f}秒)", flush=True)
                    return bytes(out)

                expect = data[:pre]
                d1, d2 = dump(pre), dump(pre)
                from collections import Counter
                for label, d in (("1回目", d1), ("2回目", d2)):
                    bad = [i for i in range(pre) if d[i] != expect[i]]
                    bits = Counter(b for i in bad for b in range(8) if (d[i] ^ expect[i]) >> b & 1)
                    hdr = sum(1 for i in bad if i % brr.BLOCK_BYTES == 0)
                    print(f"{label}: 送ったデータと違うバイト {len(bad)}/{pre} (うちブロック先頭のヘッダ{hdr}) "
                          f"化けたビット {dict(sorted(bits.items()))}")
                    for i in bad[:5]:
                        print(f"    ${RING_START + i:04X}: 送信{expect[i]:02X} 読み返し{d[i]:02X}")
                flaky = sum(1 for i in range(pre) if d1[i] != d2[i])
                print(f"1回目と2回目で読み値が違うバイト {flaky}(読み出し側の不安定さ)")
                return 0

            for reg, val in hardware.initial_dsp_writes(DIR_ADDR >> 8, args.master):
                dsp(reg, val)
            pitch = int(round(4096 * args.rate / 32000))
            for reg, val in ((0x04, 0), (0x05, 0x8F), (0x06, 0xE0), (0x02, pitch & 0xFF),
                             (0x03, pitch >> 8), (0x00, args.volume), (0x01, args.volume)):
                dsp(reg, val)
            dsp(hardware.DSP_KON, 0x01)
            t0 = time.time()
            dsp(hardware.DSP_KON, 0x00)
            print("再生開始", flush=True)

            if args.static_loop is not None:
                print(f"転送なしで{args.static_loop:.0f}秒ループ再生します(バス通信は数秒に1回の状態確認だけ)", flush=True)
                while time.time() - t0 < args.static_loop:
                    time.sleep(5)
                    envx, _ = query(4, 0x08)
                    outx, _ = query(4, 0x09)
                    print(f"  {time.time() - t0:5.1f}秒 ENVX={envx} OUTX={outx - 256 if outx > 127 else outx}", flush=True)
                dsp(hardware.DSP_KOF, 0x01)
                dsp(hardware.DSP_KOF, 0x00)
                print("完了")
                return 0

            last_report = t0
            last_diag = 0.0
            min_lead = None
            wraps = []
            last_poll = 0.0
            if args.wrap_timing:
                dsp(hardware.DSP_ENDX, 0x00)          # 書き込むとENDXは全ビット0に戻る
            if args.diag:
                diag_line(0.0)
            while sent < total:
                now = time.time()
                if args.wrap_timing and now - last_poll >= 0.03:
                    last_poll = now
                    endx, _ = query(4, hardware.DSP_ENDX)
                    if endx & 0x01:
                        dsp(hardware.DSP_ENDX, 0x00)
                        actual = now - t0
                        k = len(wraps) + 1
                        expect = k * ring_bytes / bps
                        wraps.append(actual)
                        interval = actual - (wraps[-2] if len(wraps) > 1 else 0.0)
                        print(f"  [折り返し{k}] 実測{actual:6.2f}秒 計算{expect:6.2f}秒 "
                              f"ずれ{actual - expect:+.2f}秒 (前回から{interval:.2f}秒 / 計算{ring_bytes / bps:.2f}秒)",
                              flush=True)
                if args.diag and now - t0 - last_diag >= 0.5:
                    last_diag = now - t0
                    diag_line(last_diag)
                played = (now - t0) * bps
                lead = sent - played
                min_lead = lead if min_lead is None else min(min_lead, lead)
                if lead < 0:
                    print(f"  !! 追いつかれました({lead / bps:+.2f}秒)。音が飛びます", flush=True)
                if lead < lead_bytes:
                    send_chunk(min(args.chunk, total - sent))
                else:
                    time.sleep(0.01)
                if now - last_report >= 5:
                    print(f"  {now - t0:5.1f}秒 送信{sent / 1024:6.0f}KB 先行{lead / bps:4.1f}秒 "
                          f"(最小{min_lead / bps:4.1f}秒)", flush=True)
                    last_report = now
            while (time.time() - t0) * bps < total:
                time.sleep(0.05)
            dsp(hardware.DSP_KOF, 0x01)
            dsp(hardware.DSP_KOF, 0x00)
            print(f"完了 {time.time() - t0:.1f}秒 / 先行の最小 {min_lead / bps:.2f}秒")
        finally:
            ctl.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
