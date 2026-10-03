"""Check ESP32 write latches/pads/enables; cannot observe signals after U2/U3."""
import argparse
from pathlib import Path
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spc_play import SpcController

DATA = [13, 14, 16, 17, 18, 19, 21, 22]
CONTROL = [26, 27, 23, 25, 4, 5]
MASK = sum(1 << p for p in DATA + CONTROL)
def decode_data(value):
    return sum(((value >> pin) & 1) << bit for bit, pin in enumerate(DATA))

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--trials', type=int, default=3)
a = p.parse_args()
c = SpcController(a.port, log=lambda _: None)
try:
    c.set_volume(0)
    for trial in range(a.trials):
        c.reset()
        c.ser.write(b'\x0d')
        response = c.ser.read(199)
        if len(response) != 199 or response[0] != 13:
            raise RuntimeError(f'Invalid trace response ({len(response)} bytes)')
        print(f'Trial {trial+1}: ready={response[1]}, kick ACK={response[2]}, ports={response[3:7].hex(" ")}', flush=True)
        words = struct.unpack('<48I', response[7:])
        failures = 0
        for write, (port, data) in enumerate([(2, 0), (3, 16), (1, 1), (0, 204)]):
            for stage in range(4):
                out, pads, enables = words[write*12+stage*3:write*12+stage*3+3]
                wanted = sum(1 << pin for bit, pin in enumerate(DATA) if data & (1 << bit))
                wanted |= ((port & 1) << 26) | (((port >> 1) & 1) << 27)
                wanted |= (1 << 25) | (1 << 5)
                if stage != 1: wanted |= 1 << 23
                if stage == 3: wanted |= 1 << 4
                latch_diff = (out ^ wanted) & MASK
                pad_diff = (pads ^ wanted) & MASK
                missing_enables = MASK & ~enables
                if latch_diff or pad_diff or missing_enables:
                    failures += 1
                    print(f'  write={write} port={port} data={data:02X} stage={stage}: latch diff={latch_diff:08X}, pad diff={pad_diff:08X}, missing enables={missing_enables:08X}, pad data={decode_data(pads):02X}', flush=True)
        print(f'  mismatching snapshots={failures}/16', flush=True)
finally:
    try:
        c.set_volume(0)
        c.reset()
        print(f'Final IPL: {c.read_port(0):02X}/{c.read_port(1):02X}', flush=True)
    finally:
        c.close()
