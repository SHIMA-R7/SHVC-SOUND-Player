"""Opt-in SPC gain hardware test. Keeps the saved song; leaves the requested gain."""
import argparse
import asyncio
import json
import time
from ble_player import Player
from ble_song import spc_gain_payload

async def gain(player,value):
    start=time.monotonic()
    status=await player.command(11,spc_gain_payload(value))
    assert status['mode']=='SPC' and status['spc_gain']==value,status
    print('GAIN',value,'SECONDS',round(time.monotonic()-start,2),json.dumps(status),flush=True)
    return time.monotonic()-start

async def run(args):
    spc_gain_payload(args.final_gain) # Validate before changing any device state.
    p=Player()
    try:
        await p.connect(args.address)
        print('INITIAL',json.dumps(p.last_status),flush=True)
        assert p.last_status['spc_gain_supported'] and p.last_status['mode']=='SPC'
        original_gain=p.last_status['spc_gain']
        for payload in [b'',b'\x00',b'\x01\x04']:
            try: await p.command(11,payload)
            except RuntimeError:
                assert p.last_status['code']==1 and p.last_status['spc_gain']==original_gain
            else: raise AssertionError('Invalid gain request accepted')
        assert await gain(p,0)<5
        await gain(p,.5)
        assert await gain(p,.5)<5
        await gain(p,args.final_gain)
        await p.close(); await p.connect(args.address)
        assert p.last_status['spc_gain']==args.final_gain and p.last_status['dropped']==0,p.last_status
        print('PASS invalid payload / immediate zero / half gain / no redundant reload / final gain / reconnect',flush=True)
    finally:
        await p.close()

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--address'); a.add_argument('--final-gain',type=float,default=1)
    asyncio.run(run(a.parse_args()))
