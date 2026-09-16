"""
これまで実機で再生に成功した曲(SPC / MIDI / 録音ストリーミング)をシャッフルして順に鳴らす。

  SPC  : spc_play.py で転送 → --spc-seconds 秒鳴らしてから次へ(SPCは自分では終わらないため)
  MIDI : python -m midi2spc で最後まで再生
  録音 : pcm_stream.py でストリーミング再生

使い方(SHVC-SOUND_python フォルダで実行):
  python tools/random_play.py [--port COM10] [--spc-seconds 120] [--repeat] [--list]
"""
import argparse
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY_DIR = os.path.dirname(HERE)
sys.path.insert(0, PY_DIR)
from midi2spc import hardware  # noqa: E402

ROOT = os.path.abspath(os.path.join(PY_DIR, "..", ".."))   # SHVC-SOUND フォルダ
SPC = os.path.join(ROOT, "spc")
MIDI = os.path.join(ROOT, "midi")
AUDIO = os.path.join(ROOT, "audio")
# 録音ストリーミングは librosa が要るので文字起こし用の仮想環境の python を使う
VENV_PY = os.path.join(ROOT, "tools", ".venv-transcribe", "Scripts", "python.exe")

# (表示名, 種類, ファイル, 追加オプション)
PLAYLIST = [
    ("スーパーマリオワールド / タイトル", "spc", os.path.join(SPC, "Super Mario World SNES (EMU)", "02 Title.spc"), []),
    ("スーパーマリオワールド / クッパのテーマ", "spc",
     os.path.join(SPC, "Super Mario World SNES (EMU)", "30a The Evil King Bowser.spc"), []),
    ("S.O.S. / ボイラー室", "spc", os.path.join(SPC, "S.O.S. (EMU)", "10 Boiler Room.spc"), []),
    ("SimCity / タイトル", "spc", os.path.join(SPC, "SimCity (EMU)", "01 Title.spc"), []),
    ("SimCity / メガロポリス", "spc", os.path.join(SPC, "SimCity (EMU)", "11 Megalopolis.spc"), []),
    ("SimCity / 採点", "spc", os.path.join(SPC, "SimCity (EMU)", "13 Good Evaluation.spc"), []),
    ("ぷよぷよ通 / オープニング", "spc", os.path.join(SPC, "Super Puyo Puyo Tsuu (EMU)", "01 Title.spc"), []),
    ("男はつらいよ(柴又)", "midi", os.path.join(MIDI, "shibamata_SD-90_GM2.mid"), []),
    ("CASIOPEA / ASAYAKE", "midi", os.path.join(MIDI, "CASIOPEA.Asayake.mid"), []),
    ("U.N.オーエンは彼女なのか？", "midi", os.path.join(MIDI, "UN_Owen_was_Her_SD-90.mid"), []),
    ("YO-KAI Disco", "midi", os.path.join(MIDI, "YO-KAI_Disco.mid"),
     ["--drop-channels", "2,4,5,9,14", "--lead-channels", "1", "--master", "0.28"]),
    ("ブルーアーカイブ / Unwelcome School", "midi", os.path.join(MIDI, "Unwelcome_School_reduced_sawlead.mid"),
     ["--lead-channels", "1", "--master", "0.33"]),
    ("ふたりのきもちのほんとのひみつ", "midi", os.path.join(MIDI, "Futari_no_Kimochi_SC88Pro.mid"),
     ["--lead-channels", "8,9", "--master", "0.35"]),
    ("Fatamorgana(録音ストリーミング)", "pcm", os.path.join(AUDIO, "Fatamorgana.wav"), ["--rate", "8000", "--peak", "0.8"]),
]


def command(kind, path, extra, port):
    if kind == "spc":
        return [sys.executable, os.path.join(PY_DIR, "spc_play.py"), port, path]
    if kind == "midi":
        return [sys.executable, "-m", "midi2spc", path, *extra, "--port", port]
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    return [py, os.path.join(HERE, "pcm_stream.py"), path, *extra, "--port", port]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--spc-seconds", type=float, default=120)
    ap.add_argument("--repeat", action="store_true", help="一巡したらまたシャッフルして続ける")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    songs = [s for s in PLAYLIST if os.path.exists(s[2])]
    for name, _, path, _ in PLAYLIST:
        if not os.path.exists(path):
            print(f"見つからないので除外: {name} ({path})", flush=True)
    if args.list:
        for name, kind, _, _ in songs:
            print(f"  [{kind}] {name}")
        return 0

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with hardware._keep_awake():
        while True:
            order = songs[:]
            random.shuffle(order)
            for n, (name, kind, path, extra) in enumerate(order, 1):
                print(f"\n=== {n}/{len(order)} {name} [{kind}] ===", flush=True)
                t = time.time()
                if kind == "spc":
                    r = subprocess.run(command(kind, path, extra, args.port), cwd=PY_DIR, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                       errors="replace")
                    ok = r.returncode == 0
                    if ok:
                        time.sleep(max(0.0, args.spc_seconds - (time.time() - t)))
                    else:
                        print(r.stdout[-800:], flush=True)
                else:
                    r = subprocess.run(command(kind, path, extra, args.port), cwd=PY_DIR, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                       errors="replace")
                    ok = r.returncode == 0
                    if not ok:
                        print(r.stdout[-800:], flush=True)
                print(f"    {'OK' if ok else '失敗'} {time.time() - t:.0f}秒", flush=True)
            if not args.repeat:
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
