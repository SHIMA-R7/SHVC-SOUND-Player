"""port_probe.pyの判定部分だけを使って、正常(AA BB 00 00が安定)になるまで
繰り返す。配線を触りながら実行することを想定しているので、待ち時間は短め。

使い方: python probe_retry.py [COM10] [最大試行回数(既定60)]
"""
import os, sys, time

PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # SHVC-SOUND_python
sys.path.insert(0, PY_DIR)
from spc_play import SpcController  # noqa: E402

port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
max_tries = int(sys.argv[2]) if len(sys.argv) > 2 else 60

GOOD = [0xAA, 0xBB, 0x00, 0x00]

for i in range(1, max_tries + 1):
    ctl = SpcController(port, log=lambda *_: None)
    try:
        try:
            ctl.reset()
            reset_ok = True
        except RuntimeError:
            reset_ok = False
        vals = [ctl.read_port(p) for p in range(4)]
        good = reset_ok and vals == GOOD
        print(f"#{i:3d} reset={'OK' if reset_ok else 'NG'} "
              f"port=[{' '.join(f'{v:02X}' for v in vals)}] "
              f"{'← 正常' if good else ''}", flush=True)
    finally:
        ctl.close()
    if good:
        print(f"{i}回目で安定。ここで停止します。")
        break
    time.sleep(1.5)
else:
    print(f"{max_tries}回試しても安定しませんでした。")
