"""
SPCファイルを順番に一定時間ずつ鳴らしてメドレーにする(SPCは自分では終わらないので、時間で次へ進む)。

  python tools/spc_medley.py [--seconds 75] [--port COM10] 曲1.spc 曲2.spc ...
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY_DIR = os.path.dirname(HERE)
sys.path.insert(0, PY_DIR)
from midi2spc import hardware  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=75)
    ap.add_argument("--port", default="COM10")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with hardware._keep_awake():
        for n, path in enumerate(args.files, 1):
            game = os.path.basename(os.path.dirname(path)).replace(" (EMU)", "")
            title = os.path.splitext(os.path.basename(path))[0]
            print(f"\n=== {n}/{len(args.files)} {game} / {title} ===", flush=True)
            t = time.time()
            r = subprocess.run([sys.executable, os.path.join(PY_DIR, "spc_play.py"), args.port, path], cwd=PY_DIR,
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                print("    転送に失敗しました。次の曲へ", flush=True)
                print(r.stdout[-600:], flush=True)
                continue
            print(f"    再生中 (転送 {time.time() - t:.0f}秒)", flush=True)
            time.sleep(max(0.0, args.seconds - (time.time() - t)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
