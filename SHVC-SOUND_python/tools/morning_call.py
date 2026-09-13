"""
指定時刻に、ずんだもんのモーニングコールをSHVC-SOUNDで鳴らし、続けて曲をストリーミング再生する。

待っている間はWindowsのアイドルスリープを止める(設定は変えず、このプロセスが動いている間だけ)。
ふたを閉じる・手動でスリープさせる、といった場合は止められない。

使い方(tools/.venv-transcribe の python で実行。バックグラウンドで起動しておく):
  python morning_call.py --at 06:30 --song ../audio/Fatamorgana.wav
"""
import argparse
import datetime
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # SHVC-SOUND_python
from midi2spc import hardware  # noqa: E402

WAKE_TEXT = ("おはようなのだ！朝の六時半になったのだ。起きる時間なのだ！"
             "今日もずんだもんと一緒にがんばるのだ。ほら、起きるのだー！")


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", required=True, help="鳴らす時刻 HH:MM")
    ap.add_argument("--song", required=True)
    ap.add_argument("--text", default=WAKE_TEXT)
    ap.add_argument("--repeat", type=int, default=2, help="モーニングコールを何回しゃべるか")
    ap.add_argument("--port", default="COM10")
    ap.add_argument("--engine-dir", default=None, help="VOICEVOXエンジンを展開したフォルダ")
    ap.add_argument("--voice-out", default="morning_call.wav", help="合成したモーニングコールの保存先")
    args = ap.parse_args()

    hh, mm = (int(x) for x in args.at.split(":"))
    now = datetime.datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    log(f"{target:%Y-%m-%d %H:%M} まで待機します(スリープ抑止中)")

    py = sys.executable
    with hardware._keep_awake():
        while True:
            left = (target - datetime.datetime.now()).total_seconds()
            if left <= 0:
                break
            time.sleep(min(left, 30))

        log("モーニングコール開始")
        rc = subprocess.call([py, os.path.join(HERE, "zundamon_talk.py"), args.text,
                              "--gap", "1.5", "--rate", "8000", "--repeat", str(args.repeat),
                              "--volume", "127", "--master", "127", "--port", args.port,
                              "--out", args.voice_out]
                             + (["--engine-dir", args.engine_dir] if args.engine_dir else []))
        log(f"モーニングコール終了 (終了コード {rc})")

        log(f"曲の再生開始: {args.song}")
        rc = subprocess.call([py, os.path.join(HERE, "pcm_stream.py"), args.song,
                              "--rate", "8000", "--peak", "0.8", "--port", args.port])
        log(f"曲の再生終了 (終了コード {rc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
