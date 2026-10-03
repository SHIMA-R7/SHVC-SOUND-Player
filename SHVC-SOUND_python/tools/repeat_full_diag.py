"""Retry full SPC transfers over fresh serial connections. Never execute SPC."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spc_play import SpcController, SpcFile, build_final_stub
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('port')
p.add_argument('--trials',type=int,default=10)
p.add_argument('--write-us',type=int,default=15)
p.add_argument('--output',type=Path,help='JSON result path; use a new path for each board/session')
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
song=SpcFile(root/'song.spc')
stub=build_final_stub(song,port_handshake=True)
blocks=[(2,song.ram[2:0xf0]),(0x100,song.ram[0x100:0xffc0]),(0xffc0-len(stub),stub)]
records=[]
output=a.output or root.parent/f'docs/repeat-full-{date.today().isoformat()}-{a.write_us}us.json'
for trial in range(a.trials):
    c=SpcController(a.port,log=lambda _:None)
    result={'trial':trial+1,'completed_bytes':0,'write_us':a.write_us}
    start=time.monotonic()
    sending=False
    try:
        c.set_volume(0)
        c.ser.write(bytes([14,a.write_us & 255,a.write_us >> 8]))
        if c.ser.read(3) != bytes([14,a.write_us & 255,a.write_us >> 8]):
            raise RuntimeError('Write timing command failed')
        c.reset()
        print(f'Trial {trial+1} START',flush=True)
        for addr,data in blocks:
            result['current_address']=addr
            c.set_address(addr,True)
            sending=True
            c.send_bytes(data)
            sending=False
            result['completed_bytes']+=len(data)
            print(f'Trial {trial+1}: {result["completed_bytes"]} bytes ACKed',flush=True)
        result['success']=True
    except Exception as error:
        result['success']=False
        result['error']=str(error)
        print(f'Trial {trial+1} FAILED: {ascii(str(error))}',flush=True)
    finally:
        try:
            if sending:
                c.ser.timeout=.1
                deadline=time.monotonic()+6
                while time.monotonic()<deadline: c.ser.read(4096)
                c.ser.reset_input_buffer()
                c.ser.timeout=10
            c.set_volume(0)
            c.reset()
            result['final_ipl']=[c.read_port(0),c.read_port(1)]
            c.ser.write(bytes([14,15,0]))
            if c.ser.read(3) != bytes([14,15,0]):
                raise RuntimeError('Restoring write timing failed')
        finally:
            c.close()
        result['elapsed_seconds']=round(time.monotonic()-start,2)
        records.append(result)
        output.write_text(json.dumps(records,indent=2),encoding='utf-8')
print(f'FULL SUCCESSES {sum(r["success"] for r in records)}/{len(records)}',flush=True)
