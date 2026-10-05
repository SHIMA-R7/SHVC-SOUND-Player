"""Repeated IPL start tests, no program execution; JSON evidence saved per trial."""
import argparse
import collections
import json
from pathlib import Path
import struct
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spc_play import SpcController

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('port')
parser.add_argument('--starts', type=int, default=100)
parser.add_argument('--traces', type=int, default=20)
args = parser.parse_args()
output = Path(__file__).resolve().parents[2] / 'docs' / 'repeat-start-2026-10-03.json'
records = []
pins = [13,14,16,17,18,19,21,22]
mask = sum(1 << p for p in pins + [26,27,23,25,4,5])
c = SpcController(args.port, log=lambda _:None)
started = time.monotonic()
def save():
    output.write_text(json.dumps({'port':args.port,'elapsed_seconds':round(time.monotonic()-started,2),'trials':records}, indent=2), encoding='utf-8')
try:
    c.set_volume(0)
    for trial in range(args.starts + args.traces):
        mode = 'normal' if trial < args.starts else 'trace'
        record = {'trial':trial+1,'mode':mode}
        try:
            c.reset()
            pause = [0, .01, .1][trial % 3]
            record['pause_after_reset_seconds'] = pause
            time.sleep(pause)
            if mode == 'normal':
                try:
                    c.set_address(0x1000, True)
                    record['start_ack'] = True
                except RuntimeError as error:
                    record['start_ack'] = False
                    record['error'] = str(error)
                record['ports'] = [c.read_port(p) for p in range(4)]
            else:
                c.ser.write(b'\x0d')
                response = c.ser.read(199)
                if len(response) != 199 or response[0] != 13:
                    raise RuntimeError(f'Invalid trace response {len(response)} bytes')
                record['ready'] = bool(response[1])
                record['start_ack'] = bool(response[2])
                record['ports'] = list(response[3:7])
                words = struct.unpack('<48I',response[7:])
                record['raw_trace'] = list(words)
                mismatches = []
                for write,(port,data) in enumerate([(2,0),(3,16),(1,1),(0,204)]):
                    for stage in range(4):
                        out,pads,enables = words[write*12+stage*3:write*12+stage*3+3]
                        expected = sum(1 << pin for bit,pin in enumerate(pins) if data & (1 << bit))
                        expected |= ((port & 1) << 26) | (((port >> 1) & 1) << 27) | (1 << 25) | (1 << 5)
                        if stage != 1: expected |= 1 << 23
                        if stage == 3: expected |= 1 << 4
                        differences = [(out ^ expected) & mask,(pads ^ expected) & mask,mask & ~enables]
                        if any(differences): mismatches.append({'write':write,'stage':stage,'differences':differences})
                record['gpio_mismatches'] = mismatches
        except Exception as error:
            record['fatal_error'] = str(error)
            records.append(record)
            save()
            raise
        records.append(record)
        save()
        if (trial+1) % 10 == 0:
            print(f'{trial+1}/{args.starts+args.traces}: start ACKs={sum(bool(r.get("start_ack")) for r in records)}, GPIO mismatch trials={sum(bool(r.get("gpio_mismatches")) for r in records)}',flush=True)
    print('PORT COUNTS:',dict(collections.Counter(tuple(r.get('ports',[])) for r in records)),flush=True)
finally:
    try:
        c.set_volume(0)
        c.reset()
        print(f'Final IPL: {c.read_port(0):02X}/{c.read_port(1):02X}',flush=True)
    finally:
        c.close()
        save()
        print('Log:',output,flush=True)
