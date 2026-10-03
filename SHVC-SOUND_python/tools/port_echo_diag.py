"""Execute a tiny SPC port echo loop; DSP untouched, reset on exit."""
import argparse
import collections
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spc_play import SpcController

# CLRP; MOV $F7,#$D3; loop: MOV A,$F4 / MOV $F4,A (also F5,F6); BRA loop.
# E4/C4/8F/2F opcodes checked against MAME's SPC700 implementation.
PROGRAM = bytes.fromhex('20 8F D3 F7 E4 F4 C4 F4 E4 F5 C4 F5 E4 F6 C4 F6 2F F2')
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--trials', type=int, default=3)
p.add_argument('--mirror', action='store_true', help='Copy input port0 to all three output ports')
a = p.parse_args()
if a.mirror:
    PROGRAM = bytes.fromhex('20 8F D3 F7 E4 F4 C4 F4 C4 F5 C4 F6 2F F6')
c = SpcController(a.port, log=lambda _: None)
try:
    c.set_volume(0)
    c.reset()
    c.write_block(0x1000, PROGRAM)
    c.jump_to(0x1000)
    time.sleep(.01)
    marker = c.read_port(3)
    print(f'Echo program marker: {marker:02X} (expected D3)', flush=True)
    if marker != 0xD3:
        raise RuntimeError('Echo program start not confirmed')
    for trial in range(a.trials):
        bad = 0
        bits = [0] * 8
        examples = []
        for pattern in range(256):
            expected = [pattern] * 3 if a.mirror else [pattern, pattern ^ 255, (pattern * 73 + 85) & 255]
            for port, value in enumerate(expected[:1] if a.mirror else expected):
                c.write_port(port, value)
            time.sleep(.001)
            actuals = [c.read_port(port) for port in range(3)]
            for port, (value, actual) in enumerate(zip(expected, actuals)):
                difference = actual ^ value
                if difference:
                    bad += 1
                    for bit in range(8):
                        bits[bit] += bool(difference & (1 << bit))
                    if len(examples) < 8:
                        rereads = collections.Counter(c.read_port(port) for _ in range(8))
                        marker_reads = [c.read_port(3) for _ in range(4)]
                        examples.append((pattern, port, f'{value:02X}', f'{actual:02X}', dict(rereads), marker_reads))
            if a.mirror and actuals != expected:
                c.write_port(0, pattern)
                time.sleep(.001)
                print(f'MIRROR expected={pattern:02X}, got={[f"{v:02X}" for v in actuals]}, after rewrite={[f"{c.read_port(port):02X}" for port in range(3)]}', flush=True)
        print(f'Trial {trial+1}: mismatches/768={bad}, D0..D7={bits}, examples={examples}', flush=True)
finally:
    try:
        c.set_volume(0)
        c.reset()
        print(f'Final IPL: {c.read_port(0):02X}/{c.read_port(1):02X}', flush=True)
    finally:
        c.close()
