"""Opt-in hardware test: replaces the saved song, ending with the supplied SPC."""
import argparse
import asyncio
import struct
from ble_player import Player
from ble_song import prepare_song, begin_payload

async def expect_error(player,op,payload,code):
    try:
        await player.command(op,payload)
    except RuntimeError:
        assert player.last_status['code']==code,player.last_status
    else:
        raise AssertionError('Invalid request was accepted')

async def run(args):
    player=Player()
    try:
        print('CONNECT',await player.connect(args.address),flush=True)
        print('INITIAL',player.last_status,flush=True)
        assert (await player.command(4,b'\x01'))['muted']
        assert not (await player.command(4,b'\x00'))['muted']
        if player.last_status['mode']=='SPC': await expect_error(player,5,b'\x50',1)
        assert (await player.command(6))['mode']=='MIDI live'
        await player.command(5,b'\x50')
        await player.command(7,bytes([0,10,64]))
        await player.command(10,bytes([0,0]))
        await player.midi([0x90,60,100]); await asyncio.sleep(.5); await player.midi([0x80,60,0])
        print('PASS MIDI live / master / CC / program / BLE note packets',flush=True)
        events=[(0,0xC0,0,0),(0,0x90,60,100),(500,0x80,60,0),
                (600,0x90,64,100),(1100,0x80,64,0),(1200,0x90,67,100),(1700,0x80,67,0)]
        data=struct.pack('<4sIII',b'HTM1',len(events),2000,0)+b''.join(struct.pack('<IBBBx',*e) for e in events)
        await player.upload(data)
        await player.command(8,b'\x00')
        assert (await player.command(2))['mode']=='MIDI file'
        await asyncio.sleep(2.5)
        assert (await player.command(1))['mode']=='stopped'
        print('PASS MIDI file / timed stop',flush=True)
        # Incorrect position and CRC must not replace the previously valid song.
        await player.command(16,struct.pack('<II',len(data),0))
        await expect_error(player,17,struct.pack('<I',1)+data,2)
        await player.command(17,struct.pack('<I',0)+data)
        await expect_error(player,18,b'',2)
        await player.command(19)
        assert (await player.command(2))['mode']=='MIDI file'
        await player.command(16,begin_payload(data))
        await player.command(17,struct.pack('<I',0)+data[:8])
        await player.close(); await asyncio.sleep(1); await player.connect(args.address)
        assert (await player.command(2))['mode']=='MIDI file'
        print('PASS bad offset / CRC / interrupted upload preserves saved song',flush=True)
        await player.command(3); await player.command(8,b'\x01'); await player.command(9,b'\x01')
        song=prepare_song(args.spc)
        last=[-1]
        def progress(done,total):
            pct=done*100//total
            if pct//10!=last[0]: print('SPC TRANSFER',pct,flush=True); last[0]=pct//10
        await player.upload(song,progress)
        assert (await player.command(2))['mode']=='SPC'
        print('PASS SPC persistent upload / restore',player.last_status,flush=True)
    finally:
        await player.close()
    if args.reset_port:
        import serial
        port=serial.Serial(args.reset_port,115200,timeout=1)
        port.dtr=False; port.rts=True; await asyncio.sleep(.1); port.rts=False
        print('RESET',flush=True)
        try:
            for _ in range(70):
                line=await asyncio.to_thread(port.readline)
                if line: print(line.decode(errors='replace').rstrip(),flush=True)
                if b'ACK seq=0 op=1 code=0 mode=1' in line: break
            else: raise AssertionError('SPC did not resume after ESP32 reset')
        finally: port.close()
        await asyncio.sleep(1)
        await player.connect(args.address)
        try:
            assert player.last_status['mode']=='SPC'
            print('PASS reboot / saved SPC autoplay',player.last_status,flush=True)
        finally: await player.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('spc'); p.add_argument('--address'); p.add_argument('--reset-port')
    asyncio.run(run(p.parse_args()))
