"""Test all 256 output data values at ESP32 pads while U2 is enabled."""
import argparse
import json
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from spc_play import SpcController
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--trials',type=int,default=5)
a=p.parse_args()
pins=[13,14,16,17,18,19,21,22]
mask=sum(1 << p for p in pins+[26,27,23,25,4,5])
records=[]
c=SpcController(a.port,log=lambda _:None)
try:
    c.set_volume(0)
    for trial in range(a.trials):
        c.reset()
        c.ser.write(b'\x0f')
        response=c.ser.read(3073)
        if len(response)!=3073 or response[0]!=15:
            raise RuntimeError(f'Invalid pad sweep response: {len(response)} bytes')
        words=struct.unpack('<768I',response[1:])
        failures=[]
        for value in range(256):
            expected=sum(1 << pin for bit,pin in enumerate(pins) if value & (1 << bit))
            expected |= (1 << 27) | (1 << 25) | (1 << 5)
            out,pads,enables=words[value*3:value*3+3]
            differences=[(out ^ expected)&mask,(pads ^ expected)&mask,mask & ~enables]
            if any(differences): failures.append({'value':value,'differences':differences})
        records.append({'trial':trial+1,'failures':failures,'raw_trace':list(words)})
        print(f'Trial {trial+1}: mismatching ESP32 pad snapshots={len(failures)}/256',flush=True)
finally:
    try:
        c.set_volume(0)
        c.reset()
        print(f'Final IPL: {c.read_port(0):02X}/{c.read_port(1):02X}',flush=True)
    finally:
        c.close()
        output=Path(__file__).resolve().parents[2]/'docs/pad-sweep-2026-10-03.json'
        output.write_text(json.dumps(records,indent=2),encoding='utf-8')
