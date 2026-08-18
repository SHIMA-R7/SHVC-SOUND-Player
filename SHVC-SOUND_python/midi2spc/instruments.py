#!/usr/bin/env python3
"""
instruments.py - 音色バンク(BRRサンプル + ADSR設定)

実機のSHVC-SOUNDに載せることを前提に、音色は
「32サンプルのループ波形 or 短い減衰サンプル」を BRR にエンコードした形で持つ。
サンプルレートは S-DSP の 32000Hz。

ループ波形は32サンプル = 1周期なので、ピッチ比1.0のとき 32000/32 = 1000Hz。
つまり「natural_hz = 1000」。MIDIノート107(約3951Hz)まで
S-DSPのPITCHレジスタ上限(比 4.0 未満)に収まる。
"""

import numpy as np

from . import brr


SAMPLE_RATE = 32000
LOOP_SAMPLES = 32
LOOP_NATURAL_HZ = SAMPLE_RATE / LOOP_SAMPLES   # = 1000.0


# ---- 波形生成 ---------------------------------------------------------------

def _phase():
    return np.linspace(0.0, 1.0, LOOP_SAMPLES, endpoint=False)


def _wave_square(duty=0.5):
    return np.where(_phase() < duty, 1.0, -1.0)


def _wave_saw():
    return 2.0 * _phase() - 1.0


def _wave_triangle():
    p = _phase()
    return 2.0 * np.abs(2.0 * (p - np.floor(p + 0.5))) - 1.0


def _wave_sine():
    return np.sin(2 * np.pi * _phase())


def _wave_harmonics(weights):
    """倍音を足し合わせて作る。weights[k] は第(k+1)倍音の振幅。"""
    p = _phase()
    out = np.zeros(LOOP_SAMPLES)
    for k, w in enumerate(weights, start=1):
        out += w * np.sin(2 * np.pi * k * p)
    peak = np.max(np.abs(out))
    return out / peak if peak > 0 else out


def _noise_burst(length, decay, seed=1234):
    """打楽器用の短い減衰ノイズ(ループなし)。"""
    rng = np.random.default_rng(seed)
    n = int(length)
    n += (-n) % brr.BLOCK_SAMPLES          # 16サンプル境界に切り上げ
    env = np.exp(-np.arange(n) / max(1.0, decay))
    return rng.uniform(-1.0, 1.0, n) * env


def _tone_burst(freq, length, decay, harmonics=(1.0, 0.3, 0.1)):
    """打楽器用の短い減衰トーン(タム/キック等)。"""
    n = int(length)
    n += (-n) % brr.BLOCK_SAMPLES
    t = np.arange(n) / SAMPLE_RATE
    out = np.zeros(n)
    for k, w in enumerate(harmonics, start=1):
        out += w * np.sin(2 * np.pi * freq * k * t)
    env = np.exp(-np.arange(n) / max(1.0, decay))
    peak = np.max(np.abs(out))
    return (out / peak if peak > 0 else out) * env


# ---- 音色定義 ---------------------------------------------------------------

class Instrument:
    """
    1音色ぶんの定義。

    brr_data   : BRRエンコード済みサンプル(実機ではARAMに置くデータそのもの)
    natural_hz : ピッチ比1.0で再生したときに鳴る周波数
    adsr1/adsr2: S-DSPのADSRレジスタ値($x5/$x6)
    """

    def __init__(self, name, pcm, natural_hz, ar, dr, sl, sr, loop=True, gain=1.0):
        self.name = name
        self.natural_hz = natural_hz
        self.loop = loop
        self.gain = gain
        self.brr_data = brr.encode(pcm * gain, loop=loop)
        self.adsr1 = 0x80 | ((dr & 0x07) << 4) | (ar & 0x0F)
        self.adsr2 = ((sl & 0x07) << 5) | (sr & 0x1F)
        # 復号結果はレンダラが使う(実機と同じ量子化を通した波形)
        self.pcm, self.loop_start = brr.decode(self.brr_data)


def _looped(name, wave, ar, dr, sl, sr, gain=1.0):
    return Instrument(name, wave, LOOP_NATURAL_HZ, ar, dr, sl, sr, loop=True, gain=gain)


def _oneshot(name, wave, ar, dr, sl, sr, gain=1.0):
    return Instrument(name, wave, SAMPLE_RATE, ar, dr, sl, sr, loop=False, gain=gain)


def build_bank():
    """
    音色バンクを構築して {名前: Instrument} で返す。
    BRRエンコードは総当たりなので、起動時に一度だけ作って使い回す。
    """
    bank = {}

    # --- 旋律楽器 ---
    # ADSRは (AR, DR, SL, SR)。ARが大きいほど立ち上がりが速い。
    bank["piano"] = _looped("piano", _wave_harmonics([1.0, 0.5, 0.35, 0.2, 0.12, 0.06]),
                            ar=15, dr=5, sl=3, sr=13)
    bank["epiano"] = _looped("epiano", _wave_harmonics([1.0, 0.15, 0.5, 0.08, 0.25]),
                             ar=15, dr=4, sl=4, sr=14)
    bank["organ"] = _looped("organ", _wave_harmonics([1.0, 0.0, 0.7, 0.0, 0.5, 0.0, 0.3]),
                            ar=14, dr=0, sl=7, sr=0)
    bank["guitar"] = _looped("guitar", _wave_harmonics([1.0, 0.7, 0.4, 0.45, 0.2, 0.15, 0.1]),
                             ar=15, dr=6, sl=2, sr=15)
    bank["bass"] = _looped("bass", _wave_harmonics([1.0, 0.45, 0.15, 0.05]),
                           ar=15, dr=7, sl=5, sr=12)
    bank["strings"] = _looped("strings", _wave_saw(), ar=8, dr=2, sl=6, sr=6, gain=0.85)
    bank["brass"] = _looped("brass", _wave_harmonics([1.0, 0.8, 0.6, 0.45, 0.3, 0.2, 0.12]),
                            ar=11, dr=3, sl=6, sr=8)
    bank["reed"] = _looped("reed", _wave_square(0.25), ar=12, dr=3, sl=6, sr=8, gain=0.7)
    bank["flute"] = _looped("flute", _wave_sine(), ar=10, dr=2, sl=7, sr=4, gain=0.9)
    bank["lead"] = _looped("lead", _wave_square(0.5), ar=15, dr=2, sl=6, sr=8, gain=0.7)
    bank["pad"] = _looped("pad", _wave_harmonics([1.0, 0.3, 0.6, 0.2, 0.3, 0.1]),
                          ar=6, dr=1, sl=6, sr=4, gain=0.8)
    bank["bell"] = _looped("bell", _wave_harmonics([1.0, 0.0, 0.0, 0.6, 0.0, 0.35, 0.0, 0.2]),
                           ar=15, dr=3, sl=1, sr=16)
    bank["pluck"] = _looped("pluck", _wave_triangle(), ar=15, dr=6, sl=2, sr=17)

    # --- 打楽器(ループなし) ---
    bank["kick"] = _oneshot("kick", _tone_burst(58, 2400, 420, (1.0, 0.25)), ar=15, dr=7, sl=0, sr=20)
    bank["snare"] = _oneshot("snare", _noise_burst(2000, 300, seed=7) * 0.9
                             + _tone_burst(190, 2000, 260, (1.0,)) * 0.5,
                             ar=15, dr=7, sl=0, sr=22)
    bank["hihat"] = _oneshot("hihat", _noise_burst(900, 90, seed=11), ar=15, dr=7, sl=0, sr=26)
    bank["openhat"] = _oneshot("openhat", _noise_burst(4800, 900, seed=13), ar=15, dr=7, sl=0, sr=18)
    bank["tom"] = _oneshot("tom", _tone_burst(140, 3000, 500, (1.0, 0.3)), ar=15, dr=7, sl=0, sr=19)
    bank["cymbal"] = _oneshot("cymbal", _noise_burst(9600, 2600, seed=17), ar=15, dr=7, sl=0, sr=14)
    bank["clap"] = _oneshot("clap", _noise_burst(1600, 220, seed=23), ar=15, dr=7, sl=0, sr=23)

    return bank


# ---- GM音色番号 → 音色名 ----------------------------------------------------

def _gm_map():
    """GMの128音色を、上のバンクの音色名に割り当てる。"""
    m = {}

    def assign(start, end, name):
        for p in range(start, end + 1):
            m[p] = name

    assign(0, 7, "piano")
    assign(8, 15, "bell")        # クロマチックパーカッション
    assign(16, 23, "organ")
    assign(24, 31, "guitar")
    assign(32, 39, "bass")
    assign(40, 47, "strings")
    assign(48, 55, "pad")        # アンサンブル/合唱
    assign(56, 63, "brass")
    assign(64, 71, "reed")
    assign(72, 79, "flute")
    assign(80, 87, "lead")
    assign(88, 95, "pad")
    assign(96, 103, "pad")       # シンセエフェクト
    assign(104, 111, "pluck")    # 民族楽器
    assign(112, 119, "tom")      # 打楽器系
    assign(120, 127, "pluck")    # 効果音
    m[4] = "epiano"
    m[5] = "epiano"
    return m


GM_PROGRAM_TO_NAME = _gm_map()


def _drum_map():
    """GMドラム(MIDIチャンネル10)のノート番号 → 音色名。"""
    m = {}
    for n in range(0, 128):
        m[n] = "tom"
    for n in (35, 36):
        m[n] = "kick"
    for n in (38, 40, 37):
        m[n] = "snare"
    for n in (39,):
        m[n] = "clap"
    for n in (42, 44):
        m[n] = "hihat"
    for n in (46,):
        m[n] = "openhat"
    for n in (49, 51, 52, 53, 55, 57, 59):
        m[n] = "cymbal"
    for n in (41, 43, 45, 47, 48, 50):
        m[n] = "tom"
    return m


DRUM_NOTE_TO_NAME = _drum_map()
