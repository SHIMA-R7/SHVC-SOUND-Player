"""
midi2spc - MIDIをSHVC-SOUND(SPC700 + S-DSP)で鳴らすための変換ツール

処理の流れ:
    smf.py         SMFを読んでMIDIイベント列にする
    instruments.py BRR音色バンクを組み立てる
    engine.py      MIDIイベント列 → S-DSPレジスタ操作イベント列(ここが変換の本体)
    render.py      イベント列をPC上で音にする(S-DSPのソフトウェアモデル)

engine.py の出力するイベント列が実機に送るコマンド列そのものなので、
将来 render.py の代わりにシリアル送信バックエンドを差し込めば、
同じ変換結果をそのまま実機のSHVC-SOUNDで鳴らせる。
"""

__version__ = "0.1.0"
