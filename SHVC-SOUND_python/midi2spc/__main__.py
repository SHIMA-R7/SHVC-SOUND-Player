#!/usr/bin/env python3
"""
midi2spc のコマンドラインインタフェース

使い方:
    python -m midi2spc song.mid                 # 変換して即再生
    python -m midi2spc song.mid -o out.wav      # WAVに書き出す
    python -m midi2spc song.mid --dump-events   # 送出するDSPイベントを表示
    python -m midi2spc --list-instruments       # 音色バンクの一覧
"""

import argparse
import sys
import time
import wave

import numpy as np

from . import engine, instruments, render, smf


def _write_wav(path, audio):
    """float32ステレオ(-1..1)を16bit PCMのWAVとして書き出す。"""
    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(render.SAMPLE_RATE)
        w.writeframes(pcm16.tobytes())


def _play(audio):
    """sounddeviceがあればその場で再生する。"""
    try:
        import sounddevice as sd
    except ImportError:
        print("再生には sounddevice が必要です: pip install sounddevice", file=sys.stderr)
        print("(-o out.wav でファイルに書き出すこともできます)", file=sys.stderr)
        return 1

    print(f"再生中... ({len(audio) / render.SAMPLE_RATE:.1f}秒, Ctrl+Cで停止)")
    try:
        sd.play(audio, render.SAMPLE_RATE)
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
        print("\n停止しました。")
    return 0


def _dump_events(events, limit):
    print(f"--- DSPイベント列 (先頭{limit}件 / 全{len(events)}件) ---")
    for ev in events[:limit]:
        if isinstance(ev, engine.KeyOn):
            print(f"{ev.time:8.3f}s  V{ev.voice}  KEYON  {ev.instrument:<8} "
                  f"PITCH=${ev.pitch:04X} VOL=({ev.voll:4d},{ev.volr:4d}) "
                  f"ADSR=${ev.adsr1:02X}${ev.adsr2:02X}")
        elif isinstance(ev, engine.KeyOff):
            print(f"{ev.time:8.3f}s  V{ev.voice}  KEYOFF")
        elif isinstance(ev, engine.SetPitch):
            print(f"{ev.time:8.3f}s  V{ev.voice}  PITCH  ${ev.pitch:04X}")
        elif isinstance(ev, engine.SetVolume):
            print(f"{ev.time:8.3f}s  V{ev.voice}  VOL    ({ev.voll:4d},{ev.volr:4d})")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="midi2spc",
        description="MIDIファイルをSHVC-SOUND(SPC700/S-DSP)向けに変換して鳴らす")
    p.add_argument("midi", nargs="?", help="入力MIDIファイル(.mid)")
    p.add_argument("-o", "--output", help="WAVファイルに書き出す(指定しなければ即再生)")
    p.add_argument("--master", type=float, default=0.55,
                   help="ボイス音量の全体倍率 0.0-1.0 (既定: 0.55)")
    p.add_argument("--gain", type=float, default=1.0,
                   help="出力全体のゲイン (既定: 1.0)")
    p.add_argument("--tail", type=float, default=1.0,
                   help="曲の最後に足す余韻の秒数 (既定: 1.0)")
    p.add_argument("--dump-events", type=int, nargs="?", const=60, default=None,
                   metavar="N", help="送出するDSPイベントをN件表示する(既定60)")
    p.add_argument("--port", metavar="COM3",
                   help="実機(SHVC-SOUND)のシリアルポート。指定するとPCではなく実機で鳴らす")
    p.add_argument("--no-audio", action="store_true",
                   help="音を出さない(変換の確認だけしたいとき)")
    p.add_argument("--list-instruments", action="store_true",
                   help="音色バンクの一覧を表示して終了")
    args = p.parse_args(argv)

    if args.list_instruments:
        bank = instruments.build_bank()
        print(f"{'音色名':<10} {'BRRサイズ':>8} {'素の周波数':>10}  ADSR   ループ")
        for name, inst in bank.items():
            loop = "あり" if inst.loop else "なし"
            print(f"{name:<10} {len(inst.brr_data):>6}B "
                  f"{inst.natural_hz:>10.1f}Hz  ${inst.adsr1:02X}${inst.adsr2:02X}  {loop}")
        return 0

    if not args.midi:
        p.error("MIDIファイルを指定してください(または --list-instruments)")

    t0 = time.time()
    print(f"MIDIを読み込み中: {args.midi}")
    try:
        midi_events, info = smf.parse_midi(args.midi)
    except (OSError, smf.MidiParseError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(f"  SMF format {info['format']}, {info['tracks']}トラック, "
          f"分解能 {info['division']} / MIDIイベント {len(midi_events)}件")

    print("音色バンクを構築中(BRRエンコード)...")
    bank = instruments.build_bank()

    print("S-DSPイベント列に変換中...")
    events, stats = engine.convert(midi_events, bank, master_volume=args.master)
    print(f"  ノート {stats['notes']}個 → DSPイベント {stats['events']}件, "
          f"長さ {stats['duration']:.1f}秒")
    if stats["stolen"]:
        print(f"  ボイス不足で打ち切った音: {stats['stolen']}個 "
              f"(S-DSPは8音までなので、多重和音では発生します)")

    if args.dump_events is not None:
        _dump_events(events, args.dump_events)

    if args.no_audio:
        print(f"完了 ({time.time() - t0:.1f}秒)")
        return 0

    if args.port:
        # --- 実機で鳴らす ---
        from . import hardware
        last = [-1]

        def hw_progress(done, total):
            pct = int(done / total * 100) if total else 0
            if pct != last[0]:
                last[0] = pct
                print(f"\r  {pct}%  ", end="", flush=True)

        try:
            hardware.play_on_hardware(args.port, events, bank, progress=hw_progress)
        except Exception as e:
            print(f"\n実機での再生に失敗しました: {e}", file=sys.stderr)
            return 1
        print(f"\n完了 ({time.time() - t0:.1f}秒)")
        return 0

    print("波形を合成中...")
    audio, peak = render.render(events, bank, tail=args.tail, master_volume=args.gain)
    if peak > 1.0:
        print(f"  ピークが{peak:.2f}まで振り切れたので全体を正規化しました "
              f"(--master を下げると回避できます)")
    print(f"変換完了 ({time.time() - t0:.1f}秒)")

    if args.output:
        _write_wav(args.output, audio)
        print(f"書き出しました: {args.output}")
        return 0

    return _play(audio)


if __name__ == "__main__":
    sys.exit(main())
