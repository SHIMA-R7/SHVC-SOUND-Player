"""Read-only baseline and write/read switching diagnosis; leaves SPC muted/reset."""
import argparse
import collections
from pathlib import Path
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spc_play import SpcController

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('port')
parser.add_argument('--trials', type=int, default=3)
args = parser.parse_args()
c = SpcController(args.port, log=lambda _: None)
try:
    c.set_volume(0)
    c.reset()
    values = collections.Counter((c.read_port(0), c.read_port(1)) for _ in range(128))
    print('READ-ONLY 128 pairs:', {f'{a:02X}/{b:02X}': n for (a, b), n in values.items()}, flush=True)
    for trial in range(args.trials):
        c.reset()
        c.ser.write(b'\x0c')
        response = c.ser.read(20)
        if len(response) != 20 or response[0] != 12:
            raise RuntimeError(f'Invalid diagnostic response: {response.hex()}')
        counters = struct.unpack('<9H', response[2:])
        print(f'Trial {trial+1}: GPIO flags={response[1]}, bad reads/512={counters[0]}, D0..D7={counters[1:]}', flush=True)
finally:
    try:
        c.set_volume(0)
        c.reset()
        print('Final IPL:', hex(c.read_port(0)), hex(c.read_port(1)), flush=True)
    finally:
        c.close()
