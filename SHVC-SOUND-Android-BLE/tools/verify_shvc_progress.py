"""Replay the ESP's saved song and validate real chip-transfer notifications."""
import asyncio
import json
from pathlib import Path
import struct
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'SHVC-SOUND_python/tools'))
from ble_player import Player

class Probe(Player):
    def __init__(self):
        super().__init__(); self.progress=[]
    def _notification(self,c,data):
        super()._notification(c,data)
        seq,op,code,done,total,mode,flags,volume,dropped=struct.unpack('<HBBIIBBHI',data)
        if mode==4 and flags&16:
            self.progress.append((done,total))
            if len(self.progress)%16==1 or done==total: print(f'SHVC {done}/{total}',flush=True)

async def main():
    p=Probe()
    try:
        await p.connect()
        started=time.perf_counter()
        result=await p.command(2)
        elapsed=time.perf_counter()-started
        assert result['mode']=='SPC',result
        assert len(p.progress)>3
        total=p.progress[0][1]
        assert total>0 and p.progress[0][0]==0
        assert all(t==total and 0<=done<=t for done,t in p.progress)
        assert all(a[0]<=b[0] for a,b in zip(p.progress,p.progress[1:]))
        assert p.progress[-1][0]==total
        print(json.dumps({'notifications':len(p.progress),'chipBytes':total,'finalMode':result['mode'],'monotonic':True,'elapsedSeconds':round(elapsed,3)}),flush=True)
    finally: await p.close()

asyncio.run(main())
