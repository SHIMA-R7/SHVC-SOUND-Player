"""
VOICEVOX(ずんだもん)でセリフを合成し、SHVC-SOUNDでループ再生する。

  1. ローカルのVOICEVOXエンジン(tools/voicevox_engine)を起動する(起動済みならそのまま)
  2. セリフを「ずんだもん(ノーマル)」で合成し、後ろに無音を足してWAVにする
  3. pcm_stream.py --loop-whole で、音声全体をARAMに入れてS-DSPだけでループさせる

クレジット: VOICEVOX:ずんだもん

使い方(tools/.venv-transcribe の python で実行):
  python zundamon_talk.py "しゃべらせる文" [--gap 3] [--rate 8000] [--speed 1.0] [--out 保存先.wav] [--no-play]
"""
import argparse
import glob
import io
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
# VOICEVOXエンジンの置き場所(リポジトリには含めない)。環境変数 VOICEVOX_ENGINE_DIR か --engine-dir で変えられる
ENGINE_DIR = os.environ.get("VOICEVOX_ENGINE_DIR", os.path.join(HERE, "voicevox_engine"))
URL = "http://127.0.0.1:50021"


def api(path, data=None, method="GET"):
    req = urllib.request.Request(URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def ensure_engine(engine_dir=None):
    try:
        return api("/version").decode()
    except OSError:
        pass
    engine_dir = engine_dir or ENGINE_DIR
    exes = glob.glob(os.path.join(engine_dir, "**", "run.exe"), recursive=True)
    if not exes:
        raise SystemExit(f"VOICEVOXエンジンが見つかりません: {engine_dir}")
    print(f"VOICEVOXエンジンを起動します: {exes[0]}", flush=True)
    subprocess.Popen([exes[0], "--host", "127.0.0.1", "--port", "50021"],
                     cwd=os.path.dirname(exes[0]),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(180):
        try:
            return api("/version").decode()
        except OSError:
            time.sleep(1)
    raise SystemExit("VOICEVOXエンジンが起動しません")


def zundamon_style_id(style="ノーマル"):
    for sp in json.loads(api("/speakers")):
        if sp["name"] == "ずんだもん":
            for st in sp["styles"]:
                if st["name"] == style:
                    return st["id"]
    raise SystemExit("ずんだもんの話者が見つかりません")


def synthesize(text, speaker, speed):
    q = json.loads(api(f"/audio_query?text={urllib.parse.quote(text)}&speaker={speaker}", b"", "POST"))
    q["speedScale"] = speed
    q["outputStereo"] = False
    wav = api(f"/synthesis?speaker={speaker}", json.dumps(q).encode(), "POST")
    y, sr = sf.read(io.BytesIO(wav), dtype="float32")
    return y, sr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--gap", type=float, default=3.0, help="セリフのあとの無音(秒)")
    ap.add_argument("--rate", type=int, default=8000)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--style", default="ノーマル")
    ap.add_argument("--out", default="zundamon_talk.wav", help="合成した音声の保存先")
    ap.add_argument("--engine-dir", default=None, help="VOICEVOXエンジンを展開したフォルダ")
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--no-play", action="store_true")
    ap.add_argument("--repeat", type=int, default=0,
                    help="何回しゃべったら止めるか(0=止めるまでループ)")
    ap.add_argument("--volume", type=int, default=110)
    ap.add_argument("--master", type=int, default=0x7F)
    args = ap.parse_args()

    print("VOICEVOX", ensure_engine(args.engine_dir), flush=True)
    speaker = zundamon_style_id(args.style)
    y, sr = synthesize(args.text, speaker, args.speed)
    y = np.concatenate([y, np.zeros(int(sr * args.gap), dtype=np.float32)])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    sf.write(args.out, y, sr)
    print(f"合成しました: {args.out} (セリフ{len(y) / sr - args.gap:.1f}秒 + 無音{args.gap:g}秒)", flush=True)

    if args.no_play:
        return 0
    py = sys.executable
    cmd = [py, os.path.join(HERE, "pcm_stream.py"), args.out, "--rate", str(args.rate),
           "--peak", "0.8", "--loop-whole", "--port", args.port,
           "--volume", str(args.volume), "--master", str(args.master)]
    if args.repeat > 0:
        cmd += ["--static-loop", f"{len(y) / sr * args.repeat:.2f}"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
