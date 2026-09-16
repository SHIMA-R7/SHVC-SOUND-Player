"""
ステレオ録音をミッド/サイドに分け、SHVC-SOUNDの2ボイスでストリーミング再生する。

  ボイス0 = ミッド((L+R)/2)  VOLL=+v, VOLR=+v   高いサンプルレート
  ボイス1 = サイド((L-R)/2)  VOLL=+v, VOLR=-v   低いサンプルレートでよい(左右差の成分は高音が少ない)
  → S-DSPの中で L = ミッド+サイド, R = ミッド-サイド に組み上がる(配線はステレオ出力のまま)

ARAMのリングはページ境界で2本に分ける(pcm_stream.py の一括受信モード・リング切り替えを使う)。
  リング0(ミッド): $0400-$B7FF / リング1(サイド): $B800-$F6FF / サンプルディレクトリ: $F700

使い方(tools/.venv-transcribe の python で実行):
  python pcm_stereo.py 曲.wav [--mid-rate 16000] [--side-rate 6000] [--seconds 60] [--predictive]
"""
import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import pcm_stream as ps  # noqa: E402
from midi2spc import brr, hardware  # noqa: E402

# ページ数は9の倍数にする(9バイト単位のBRRブロックでちょうど割り切れる)
RINGS = [(0x04, 0xB8), (0xB8, 0xF7)]


def ring_blocks(i):
    start, end = RINGS[i]
    return (end - start) * 256 // brr.BLOCK_BYTES


def flags_for(data, blocks):
    out = bytearray(data)
    for j in range(len(out) // brr.BLOCK_BYTES):
        h = j * brr.BLOCK_BYTES
        out[h] &= 0xFC
        if j % blocks == blocks - 1:
            out[h] |= 0x03
    return out


def silence(first_block, count, blocks):
    tail = bytearray()
    for j in range(first_block, first_block + count):
        tail += bytes([0x03 if j % blocks == blocks - 1 else 0x00]) + bytes(8)
    return tail


def encode(y, predictive):
    return brr.encode(y, loop=False) if predictive else ps.encode_filter0(y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--mid-rate", type=int, default=16000)
    ap.add_argument("--side-rate", type=int, default=6000)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--peak", type=float, default=0.85)
    ap.add_argument("--predictive", action="store_true", help="予測ありBRR(きれいだが変換が遅い)")
    ap.add_argument("--volume", type=int, default=110)
    ap.add_argument("--master", type=int, default=0x7F)
    ap.add_argument("--lead", type=float, default=3.0)
    ap.add_argument("--mono-check", action="store_true", help="サイドを鳴らさずミッドだけにする(比較用)")
    ap.add_argument("--port", default="COM10")
    args = ap.parse_args()

    import librosa
    y, sr = librosa.load(args.wav, sr=None, mono=False, offset=args.start, duration=args.seconds)
    if y.ndim == 1:
        y = np.stack([y, y])
    mid, side = (y[0] + y[1]) / 2, (y[0] - y[1]) / 2
    scale = args.peak / (np.max(np.abs(mid) + np.abs(side)) + 1e-9)
    side_ratio = float(np.sqrt(np.mean(side ** 2)) / (np.sqrt(np.mean(mid ** 2)) + 1e-9))
    rates = [args.mid_rate, args.side_rate]
    streams = []
    t = time.time()
    for i, sig in enumerate((mid, side)):
        z = librosa.resample(sig * scale, orig_sr=sr, target_sr=rates[i])
        streams.append(flags_for(encode(z, args.predictive), ring_blocks(i)))
    print(f"{y.shape[1] / sr:.1f}秒 / サイドの大きさはミッドの{side_ratio * 100:.0f}% / "
          f"ミッド{args.mid_rate}Hz {len(streams[0]) / 1024:.0f}KB, サイド{args.side_rate}Hz "
          f"{len(streams[1]) / 1024:.0f}KB (変換{time.time() - t:.0f}秒)", flush=True)

    bps = [r * brr.BLOCK_BYTES / brr.BLOCK_SAMPLES for r in rates]
    ring_bytes = [ring_blocks(i) * brr.BLOCK_BYTES for i in range(2)]
    for i in range(2):
        n = len(streams[i]) // brr.BLOCK_BYTES
        streams[i] += silence(n, int(bps[i] * 0.5 / brr.BLOCK_BYTES) + 1, ring_blocks(i))
    lead_target = [min(args.lead, 0.75 * ring_bytes[i] / bps[i]) for i in range(2)]
    print(f"必要な転送量 毎秒{sum(bps) / 1024:.1f}KB / リング {ring_bytes[0] / bps[0]:.1f}秒, "
          f"{ring_bytes[1] / bps[1]:.1f}秒ぶん / 先行 {lead_target[0]:.1f}秒", flush=True)

    from spc_play import SpcController
    ctl = SpcController(args.port, log=lambda *a: None)
    ser = ctl.ser

    def dsp(reg, val):
        ser.write(bytes([ps.CMD_DSPWRITE, reg & 0xFF, val & 0xFF]))
        if ser.read(1) != bytes([ps.ACK_DSPWRITE]):
            raise RuntimeError(f"DSP書き込み失敗 ${reg:02X}")

    def query(cmd, a=0, b=0):
        ser.write(bytes([ps.CMD_DRVQUERY, cmd, a, b]))
        r = ser.read(3)
        if len(r) != 3 or r[0] != ps.CMD_DRVQUERY:
            raise RuntimeError(f"ドライバ問い合わせ失敗 cmd={cmd} 応答={r!r}")
        return r[1], r[2]

    sent = [0, 0]

    def send(i, n):
        chunk = streams[i][sent[i]:sent[i] + n]
        if len(chunk) >= 3:
            chunk = chunk[:len(chunk) - len(chunk) % 3]
            ser.write(bytes([ps.CMD_PCMBULK, len(chunk)]) + chunk)
            ok = bytes([ps.CMD_PCMBULK])
        else:
            ser.write(bytes([ps.CMD_PCMCHUNK, len(chunk)]) + chunk)
            ok = bytes([ps.ACK_PCMCHUNK])
        if ser.read(1) != ok:
            raise RuntimeError(f"PCM転送失敗 リング{i} 送信済み{sent[i]}")
        sent[i] += len(chunk)

    with hardware._keep_awake():
        try:
            ctl.reset()
            starts = [RINGS[i][0] << 8 for i in range(2)]
            directory = b"".join(bytes([s & 0xFF, s >> 8, s & 0xFF, s >> 8]) for s in starts)
            ctl.write_block(ps.DIR_ADDR, directory)
            ptrs = []
            for i in range(2):
                pre = int(lead_target[i] * bps[i])
                pre -= pre % 9
                pre = min(pre, len(streams[i]))
                ctl.write_block(starts[i], bytes(streams[i][:pre]))
                sent[i] = pre
                ptrs.append(starts[i] + pre)
            a_s, a_e = RINGS[0]
            b_s, b_e = RINGS[1]
            zp = bytes([ptrs[0] & 0xFF, ptrs[0] >> 8, 0, a_s, 0, a_e, 0]) + bytes(7) + \
                bytes([ptrs[0] & 0xFF, ptrs[0] >> 8, a_s, a_e, ptrs[1] & 0xFF, ptrs[1] >> 8, b_s, b_e])
            ctl.write_block(0x0002, zp)                    # $02-$17
            ctl.write_block(ps.DRIVER_ADDR, ps.PCM_DRIVER)
            ctl.jump_to(ps.DRIVER_ADDR)
            time.sleep(0.05)
            query(5, ptrs[0] & 0xFF, ptrs[0] >> 8)         # 起動直後の誤認書き込みを打ち消す
            lo, hi = query(3)
            if (lo | hi << 8) != ptrs[0]:
                raise RuntimeError("書き込みポインタを合わせられません")
            ser.write(bytes([ps.CMD_BULKTIMING, 1, 1, 1]))
            ser.read(1)
            current = 0

            for reg, val in hardware.initial_dsp_writes(ps.DIR_ADDR >> 8, args.master):
                dsp(reg, val)
            side_vol = 0 if args.mono_check else args.volume
            for v, pitch, voll, volr in ((0, 4096 * rates[0] // 32000, args.volume, args.volume),
                                         (1, 4096 * rates[1] // 32000, side_vol, (-side_vol) & 0xFF)):
                base = v << 4
                for reg, val in ((4, v), (5, 0x8F), (6, 0xE0), (2, pitch & 0xFF), (3, pitch >> 8),
                                 (0, voll), (1, volr)):
                    dsp(base | reg, val)
            dsp(hardware.DSP_KON, 0x03)
            t0 = time.time()
            dsp(hardware.DSP_KON, 0x00)
            print("再生開始", flush=True)

            min_lead = [9.0, 9.0]
            last = t0
            while sent[0] < len(streams[0]) or sent[1] < len(streams[1]):
                el = time.time() - t0
                leads = [(sent[i] - el * bps[i]) / bps[i] for i in range(2)]
                for i in range(2):
                    min_lead[i] = min(min_lead[i], leads[i])
                todo = [i for i in range(2) if sent[i] < len(streams[i]) and leads[i] < lead_target[i]]
                if not todo:
                    time.sleep(0.005)
                else:
                    i = min(todo, key=lambda k: leads[k])
                    if i != current:
                        query(8, i)
                        current = i
                    for _ in range(4):                     # 切り替えの往復を減らすため続けて送る
                        el = time.time() - t0
                        if sent[i] >= len(streams[i]) or (sent[i] - el * bps[i]) / bps[i] >= lead_target[i]:
                            break
                        send(i, 255)
                if time.time() - last >= 5:
                    last = time.time()
                    print(f"  {last - t0:5.1f}秒 先行 ミッド{leads[0]:.2f}秒 サイド{leads[1]:.2f}秒 "
                          f"(最小 {min_lead[0]:.2f} / {min_lead[1]:.2f})", flush=True)
            while (time.time() - t0) * bps[0] < len(streams[0]):
                time.sleep(0.05)
            dsp(hardware.DSP_KOF, 0x03)
            dsp(hardware.DSP_KOF, 0x00)
            print(f"完了 {time.time() - t0:.1f}秒 / 先行の最小 ミッド{min_lead[0]:.2f}秒 サイド{min_lead[1]:.2f}秒")
        finally:
            ctl.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
