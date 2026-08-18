#!/usr/bin/env python3
"""
render.py - DSPイベント列をPC上で音にする(S-DSPのソフトウェアモデル)

実機のSHVC-SOUNDが受け取るのと同じイベント列を入力にして、
S-DSPが出すであろう波形を32kHzステレオで合成する。

再現しているもの:
  * BRRによる4bit量子化(サンプルは brr.py で実際にエンコード/デコード済み)
  * 32kHz固定のサンプルレートと、4タップ補間による高音のなまり
  * PITCHレジスタ(14bit)によるピッチ、ADSRエンベロープ、8ボイス制限
  * 符号付き8bitのVOLL/VOLRと左右独立の音量

再現していないもの(意図的な簡略化):
  * サイクル精度のDSP動作(ここは「ノート単位」でまとめて合成している)
  * エコー/FIRフィルタ、ピッチモジュレーション、ノイズジェネレータ
  * 補間テーブルは実機の512エントリ表そのものではなくガウス窓による近似
"""

import numpy as np

from .engine import KeyOn, KeyOff, SetPitch, SetVolume, PITCH_UNITY


SAMPLE_RATE = 32000
ENV_MAX = 2047.0

# ADSRのレート番号 → エンベロープ更新周期(サンプル数)。0は「更新しない」。
RATE_TABLE = [
    0, 2048, 1536, 1280, 1024, 768, 640, 512,
    384, 320, 256, 192, 160, 128, 96, 80,
    64, 48, 40, 32, 24, 20, 16, 12,
    10, 8, 6, 5, 4, 3, 2, 1,
]

# キーオフ後の減衰。実機は毎サンプル env -= 8 なので 2048/8 = 256サンプル(8ms)。
RELEASE_SAMPLES = 256


# ---- 4タップ補間テーブル ----------------------------------------------------

def _build_interp_table():
    """
    S-DSPのガウス補間に相当する4タップの重み表を作る。

    実機は512エントリの固定テーブルを持つが、ここではガウス窓で近似する。
    fracを8bit(256段階)に量子化するところは実機と揃えてある。
    """
    fracs = np.arange(256) / 256.0
    # 補間位置は idx と idx+1 の間。4タップは idx-1, idx, idx+1, idx+2。
    offsets = np.array([-1.0, 0.0, 1.0, 2.0])
    dist = offsets[None, :] - fracs[:, None]
    sigma = 0.85
    weights = np.exp(-(dist ** 2) / (2 * sigma ** 2))
    weights /= weights.sum(axis=1, keepdims=True)
    return weights.astype(np.float32)


INTERP_TABLE = _build_interp_table()


# ---- ADSRエンベロープ -------------------------------------------------------

def _envelope(n_total, key_off_sample, adsr1, adsr2):
    """
    ADSRレジスタ値から、0.0-1.0のエンベロープ配列(長さn_total)を作る。

    実機のDECAY/SUSTAINは「更新周期ごとに env -= (env>>8)+1」という指数減衰。
    ここでは1サンプルあたりの減衰係数に直して閉じた形で計算する
    (形は同じで、サンプル単位のループを回さずに済む)。
    """
    env = np.zeros(n_total, dtype=np.float32)
    if n_total <= 0:
        return env

    use_adsr = bool(adsr1 & 0x80)
    ar = adsr1 & 0x0F
    dr = (adsr1 >> 4) & 0x07
    sl = (adsr2 >> 5) & 0x07
    sr = adsr2 & 0x1F

    sustain_level = min(1.0, (sl + 1) / 8.0)
    n_hold = max(0, min(key_off_sample, n_total))
    pos = 0
    level = 0.0

    if not use_adsr:
        env[:n_hold] = 1.0
        level = 1.0
        pos = n_hold
    else:
        # --- アタック: 更新周期ごとに +32(AR=15のときだけ +1024) ---
        if ar >= 15:
            attack_len = 2
        else:
            period = RATE_TABLE[ar * 2 + 1]
            attack_len = int(np.ceil(ENV_MAX / 32.0 * period))
        attack_len = max(1, min(attack_len, n_hold))
        env[:attack_len] = np.linspace(0.0, 1.0, attack_len, endpoint=False, dtype=np.float32)
        pos = attack_len
        level = 1.0

        # --- ディケイ: サステインレベルまで指数減衰 ---
        if pos < n_hold and sustain_level < 1.0:
            period = RATE_TABLE[dr * 2 + 16]
            if period > 0:
                per_sample = (1.0 - 1.0 / 256.0) ** (1.0 / period)
                need = int(np.ceil(np.log(sustain_level) / np.log(per_sample)))
                decay_len = max(1, min(need, n_hold - pos))
                t = np.arange(decay_len, dtype=np.float32)
                env[pos:pos + decay_len] = level * (per_sample ** t)
                level = float(env[pos + decay_len - 1])
                pos += decay_len

        # --- サステイン: SRで指数減衰(SR=0なら減衰しない) ---
        if pos < n_hold:
            period = RATE_TABLE[sr]
            if period == 0:
                env[pos:n_hold] = level
            else:
                per_sample = (1.0 - 1.0 / 256.0) ** (1.0 / period)
                t = np.arange(n_hold - pos, dtype=np.float32)
                env[pos:n_hold] = level * (per_sample ** t)
                level = float(env[n_hold - 1]) if n_hold > pos else level
            pos = n_hold

    # --- リリース: キーオフ後は8msで直線的に0へ ---
    if pos < n_total:
        rel_len = min(RELEASE_SAMPLES, n_total - pos)
        env[pos:pos + rel_len] = np.linspace(level, 0.0, rel_len, endpoint=False, dtype=np.float32)
        # それ以降は0のまま

    return env


# ---- サンプル読み出し(ループ + 補間) --------------------------------------

def _read_samples(pcm, loop_start, positions):
    """
    小数位置 positions からサンプルを4タップ補間で読み出す。
    loop_start が None ならサンプル末尾以降は無音。
    """
    n_src = len(pcm)
    idx = np.floor(positions).astype(np.int64)
    frac = positions - idx
    fi = np.minimum((frac * 256).astype(np.int64), 255)
    weights = INTERP_TABLE[fi]                      # (n, 4)

    out = np.zeros(len(positions), dtype=np.float32)
    if loop_start is None:
        alive = idx < n_src
    else:
        alive = np.ones(len(positions), dtype=bool)

    loop_len = (n_src - loop_start) if loop_start is not None else 0

    for tap in range(4):
        t_idx = idx + (tap - 1)
        if loop_start is not None and loop_len > 0:
            over = t_idx >= n_src
            t_idx = np.where(over,
                             loop_start + np.mod(t_idx - loop_start, loop_len),
                             t_idx)
        t_idx = np.clip(t_idx, 0, n_src - 1)
        out += pcm[t_idx] * weights[:, tap]

    out *= alive
    return out


# ---- イベント列 → ノート区間 ------------------------------------------------

class _Note:
    __slots__ = ("instrument", "start", "end", "adsr1", "adsr2", "spans")

    def __init__(self, ev: KeyOn):
        self.instrument = ev.instrument
        self.start = ev.time
        self.end = None
        self.adsr1 = ev.adsr1
        self.adsr2 = ev.adsr2
        # (開始時刻, pitch, voll, volr) の並び。pitch/vol変更のたびに増える。
        self.spans = [[ev.time, ev.pitch, ev.voll, ev.volr]]


def _collect_notes(events):
    """ボイスごとにKeyOn〜KeyOffをまとめて、ノート単位のリストにする。"""
    notes = []
    current = {}

    for ev in events:
        if isinstance(ev, KeyOn):
            prev = current.get(ev.voice)
            if prev is not None and prev.end is None:
                prev.end = ev.time
            note = _Note(ev)
            current[ev.voice] = note
            notes.append(note)
        elif isinstance(ev, KeyOff):
            note = current.get(ev.voice)
            if note is not None and note.end is None:
                note.end = ev.time
                current[ev.voice] = None
        elif isinstance(ev, SetPitch):
            note = current.get(ev.voice)
            if note is not None and note.end is None:
                last = note.spans[-1]
                note.spans.append([ev.time, ev.pitch, last[2], last[3]])
        elif isinstance(ev, SetVolume):
            note = current.get(ev.voice)
            if note is not None and note.end is None:
                last = note.spans[-1]
                note.spans.append([ev.time, last[1], ev.voll, ev.volr])

    for note in notes:
        if note.end is None:
            note.end = note.start
    return notes


# ---- レンダリング本体 -------------------------------------------------------

def render(events, bank, tail=1.0, master_volume=1.0, progress=None):
    """
    DSPイベント列を (n, 2) のfloat32ステレオ波形にする。

    tail     : 最後のノートが切れたあと、余韻のために足す秒数
    progress : progress(done:int, total:int) 合成済み/全体のノート数
    """
    notes = _collect_notes(events)
    if not notes:
        return np.zeros((1, 2), dtype=np.float32)

    duration = max(n.end for n in notes) + tail
    total = int(duration * SAMPLE_RATE) + RELEASE_SAMPLES + 8
    left = np.zeros(total, dtype=np.float32)
    right = np.zeros(total, dtype=np.float32)

    for note_index, note in enumerate(notes):
        if progress is not None and note_index % 32 == 0:
            progress(note_index, len(notes))

        inst = bank.get(note.instrument)
        if inst is None:
            continue

        start_sample = int(note.start * SAMPLE_RATE)
        hold_samples = max(1, int((note.end - note.start) * SAMPLE_RATE))
        n_total = hold_samples + RELEASE_SAMPLES
        if start_sample >= total:
            continue
        n_total = min(n_total, total - start_sample)
        if n_total <= 0:
            continue

        env = _envelope(n_total, hold_samples, note.adsr1, note.adsr2)

        # pitch/volが一定な区間ごとに分けて波形を読み出す
        bounds = []
        for i, span in enumerate(note.spans):
            s0 = max(0, int((span[0] - note.start) * SAMPLE_RATE))
            bounds.append((s0, span[1], span[2], span[3]))
        bounds.append((n_total, 0, 0, 0))

        phase = 0.0
        for i in range(len(bounds) - 1):
            s0, pitch, voll, volr = bounds[i]
            s1 = min(bounds[i + 1][0], n_total)
            if s1 <= s0:
                continue
            n = s1 - s0
            ratio = pitch / PITCH_UNITY
            positions = phase + ratio * np.arange(n, dtype=np.float64)
            phase = positions[-1] + ratio

            wave = _read_samples(inst.pcm, inst.loop_start, positions)
            wave = wave * env[s0:s1]

            dst0 = start_sample + s0
            dst1 = dst0 + n
            left[dst0:dst1] += wave * (voll / 127.0)
            right[dst0:dst1] += wave * (volr / 127.0)

    if progress is not None:
        progress(len(notes), len(notes))

    left *= master_volume
    right *= master_volume

    peak = float(max(np.max(np.abs(left)), np.max(np.abs(right)), 1e-9))
    clipped = peak > 1.0
    if clipped:
        # 実機なら飽和して歪むところ。PCでは聴きやすさを優先して全体を下げる。
        left /= peak
        right /= peak

    return np.stack([left, right], axis=1), peak
