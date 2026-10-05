"""Slow IPL write/ack test; no program execution, mute and reset on exit."""
import argparse
import collections
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spc_play import SpcController

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--count', type=int, default=512)
a = p.parse_args()
c = SpcController(a.port, log=lambda _: None)
try:
    c.set_volume(0)
    c.reset()
    c.set_address(0x1000, True)
    for pos in range(a.count):
        token = pos & 255
        data = (pos * 73 + 0x55) & 255
        c.write_port(1, data)
        c.write_port(0, token)
        seen = collections.Counter()
        deadline = time.monotonic() + .25
        while True:
            value = c.read_port(0)
            seen[value] += 1
            if value == token:
                break
            if time.monotonic() >= deadline:
                break
        if value != token:
            print(f'STALLED pos={pos} data={data:02X} expected={token:02X} reads={dict(seen)}', flush=True)
            # Observe first; do not alter token/data if the device may have accepted it.
            snapshot = collections.Counter(c.read_port(0) for _ in range(32))
            print('32 additional reads:', dict(snapshot), flush=True)
            if set(snapshot) == {(token - 1) & 255}:
                c.write_port(1, data)
                c.write_port(0, token)
                after = collections.Counter(c.read_port(0) for _ in range(32))
                print('After same data/token re-write:', dict(after), flush=True)
            break
        if (pos + 1) % 128 == 0:
            print(f'ACK OK {pos + 1}/{a.count}', flush=True)
    else:
        print('ALL WRITE ACKS OK (not RAM readback)', flush=True)
finally:
    try:
        c.set_volume(0)
        c.reset()
        print(f'Final IPL: {c.read_port(0):02X}/{c.read_port(1):02X}', flush=True)
    finally:
        c.close()
