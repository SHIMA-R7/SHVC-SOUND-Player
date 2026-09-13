"""SPC700の$F4-$F7ポートを覗いて、リセット前後で何が見えているかを確認する診断。

使い方: python port_probe.py [COM10]
"""
import os, sys, time

PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # SHVC-SOUND_python
sys.path.insert(0, PY_DIR)
from spc_play import SpcController  # noqa: E402

port = sys.argv[1] if len(sys.argv) > 1 else "COM10"
ctl = SpcController(port, log=lambda *_: None)


def snapshot(label, n=8, interval=0.1):
    print(f"--- {label}")
    for _ in range(n):
        vals = [ctl.read_port(p) for p in range(4)]
        print("   " + " ".join(f"{v:02X}" for v in vals))
        time.sleep(interval)


try:
    snapshot("リセット前 (port0 port1 port2 port3)")
    t = time.time()
    try:
        ctl.reset()
        print(f"リセット成功 ({time.time() - t:.1f}s)")
    except RuntimeError as e:
        print(f"リセット失敗 ({time.time() - t:.1f}s): {e}")
    snapshot("リセット後")
finally:
    ctl.close()
