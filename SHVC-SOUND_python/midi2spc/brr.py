#!/usr/bin/env python3
"""
brr.py - BRR (Bit Rate Reduction) サンプルのエンコード/デコード

SPC700の音源はPCMをそのまま鳴らせず、BRRという4bit ADPCM形式しか読めない。
本物の実機に載せる音色データも最終的にはこの形式になるので、PC上の
シミュレーションでも同じ経路を通しておく(＝実機と同じ量子化ノイズが乗る)。

BRRブロック構造(1ブロック = 9バイト = 16サンプル):
    バイト0 : ヘッダ  [range(4bit) | filter(2bit) | loop(1bit) | end(1bit)]
    バイト1-8: 4bit符号付きサンプル × 16 (上位ニブルが先)

デコード式(filterごとに直前2サンプルから予測):
    filter 0: s = n
    filter 1: s = n +  p1        - p1/16
    filter 2: s = n + 2*p1       - p1*3/32  - p2      + p2/16
    filter 3: s = n + 2*p1       - p1*13/64 - p2 + p2*3/16
"""

import numpy as np


BLOCK_SAMPLES = 16
BLOCK_BYTES = 9


def _apply_filter(nibble_value, p1, p2, filt):
    """1サンプル分の予測復号。p1/p2は直前・2つ前の復号済みサンプル。"""
    if filt == 0:
        return nibble_value
    if filt == 1:
        return nibble_value + p1 - (p1 >> 4)
    if filt == 2:
        return nibble_value + 2 * p1 - (p1 * 3 >> 5) - p2 + (p2 >> 4)
    return nibble_value + 2 * p1 - (p1 * 13 >> 6) - p2 + (p2 * 3 >> 4)


def _clamp16(v):
    """S-DSPの内部は符号付き16bitで飽和する。"""
    if v > 32767:
        return 32767
    if v < -32768:
        return -32768
    return v


def _clip15(v):
    """BRR復号後は15bitでラップする(実機の挙動)。ここでは飽和で近似する。"""
    return _clamp16(v)


def encode_block(samples, p1, p2, is_loop_block, is_end_block):
    """
    16サンプル(符号付き16bit相当のint配列)を1ブロックにエンコードする。

    range と filter の全組み合わせ(13 × 4)を実際に試して、
    復号誤差が最小になったものを採用する総当たり方式。
    サンプル数が少ないので速度は問題にならず、品質は素直に良い。

    戻り値: (9バイトのbytes, 復号後のp1, 復号後のp2)
    """
    best = None
    # filter 1-3 は直前サンプルを参照するので、ブロック先頭では filter 0 のみ有効
    filters = (0,) if (p1 == 0 and p2 == 0) else (0, 1, 2, 3)

    for filt in filters:
        for rng in range(13):  # range 13-15 は実機で異常動作するので使わない
            err = 0
            nibbles = []
            a, b = p1, p2
            for s in samples:
                # 予測値を引いた残差を range でスケールして4bitに丸める
                pred = _apply_filter(0, a, b, filt)
                residual = s - pred
                if rng == 0:
                    n = int(round(residual))
                else:
                    n = int(round(residual / (1 << rng)))
                n = max(-8, min(7, n))
                nibbles.append(n)

                shifted = (n << rng) >> 1 if rng > 0 else (n >> 1)
                decoded = _clip15(_apply_filter(shifted * 2, a, b, filt))
                err += (decoded - s) ** 2
                a, b = decoded, a

            if best is None or err < best[0]:
                best = (err, rng, filt, nibbles, a, b)

    _, rng, filt, nibbles, new_p1, new_p2 = best
    header = (rng << 4) | (filt << 2) | (2 if is_loop_block else 0) | (1 if is_end_block else 0)
    body = bytearray([header])
    for i in range(0, BLOCK_SAMPLES, 2):
        hi = nibbles[i] & 0x0F
        lo = nibbles[i + 1] & 0x0F
        body.append((hi << 4) | lo)
    return bytes(body), new_p1, new_p2


def encode(pcm, loop=True):
    """
    PCM(-1.0..1.0のfloat配列、長さは16の倍数)をBRRデータにエンコードする。

    loop=True のとき、最終ブロックに loop フラグと end フラグを立て、
    ループ先頭は「サンプル全体の先頭」とする(このツールの音色は
    全体がループ波形なので、ループポイント=0で足りる)。
    """
    pcm = np.asarray(pcm, dtype=np.float64)
    if len(pcm) % BLOCK_SAMPLES != 0:
        pad = BLOCK_SAMPLES - (len(pcm) % BLOCK_SAMPLES)
        pcm = np.concatenate([pcm, np.zeros(pad)])

    ints = np.clip(np.round(pcm * 32767.0), -32768, 32767).astype(np.int64)
    nblocks = len(ints) // BLOCK_SAMPLES

    out = bytearray()
    p1 = p2 = 0
    for bi in range(nblocks):
        chunk = ints[bi * BLOCK_SAMPLES:(bi + 1) * BLOCK_SAMPLES]
        is_last = (bi == nblocks - 1)
        block, p1, p2 = encode_block(list(chunk), p1, p2,
                                     is_loop_block=(is_last and loop),
                                     is_end_block=is_last)
        out += block
    return bytes(out)


def decode(brr_data):
    """
    BRRデータを復号して (PCM float配列, ループ開始位置 or None) を返す。

    end フラグの立ったブロックで終了する。loop フラグも立っていれば
    ループあり(このモジュールが作るデータではループ開始位置は常に0)。
    """
    samples = []
    p1 = p2 = 0
    looped = False

    for pos in range(0, len(brr_data) - BLOCK_BYTES + 1, BLOCK_BYTES):
        header = brr_data[pos]
        rng = header >> 4
        filt = (header >> 2) & 0x03
        loop_flag = bool(header & 0x02)
        end_flag = bool(header & 0x01)

        for i in range(BLOCK_SAMPLES):
            byte = brr_data[pos + 1 + i // 2]
            nib = (byte >> 4) if (i % 2 == 0) else (byte & 0x0F)
            if nib >= 8:
                nib -= 16  # 4bit符号付き

            shifted = (nib << rng) >> 1 if rng > 0 else (nib >> 1)
            value = _clip15(_apply_filter(shifted * 2, p1, p2, filt))
            samples.append(value)
            p1, p2 = value, p1

        if end_flag:
            looped = loop_flag
            break

    pcm = np.asarray(samples, dtype=np.float32) / 32768.0
    return pcm, (0 if looped else None)
