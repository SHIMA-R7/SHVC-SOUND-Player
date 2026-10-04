"""Windows-friendly BLE client: scan, controls, persistent SPC/MIDI, live BLE MIDI."""
import argparse
import asyncio
import json
from pathlib import Path
import struct
import time
from ble_song import SERVICE, COMMAND, STATUS, MIDI_CHAR, parse_reply, prepare_song, chunks, begin_payload

class Player:
    def __init__(self):
        self.client = None
        self.sequence = 0
        self.pending = {}
        self.last_status = {}
        self.lock = asyncio.Lock()

    async def connect(self, address=None):
        from bleak import BleakClient, BleakScanner
        if address:
            device = await BleakScanner.find_device_by_address(address, timeout=15)
        else:
            device = await BleakScanner.find_device_by_filter(
                lambda d,a: SERVICE in [u.lower() for u in a.service_uuids], timeout=15)
        if device is None:
            raise RuntimeError('SHVC-SOUND Player not found. Check power and Windows Bluetooth.')
        self.client = BleakClient(device, timeout=30, disconnected_callback=self._disconnected)
        await self.client.connect()
        try:
            await self.client.start_notify(STATUS, self._notification)
            await self.command(1)
        except BaseException:
            await self.close()
            raise
        return device

    def _disconnected(self, client):
        for future in list(self.pending.values()):
            if not future.done(): future.set_exception(ConnectionError('Bluetooth disconnected'))

    def _notification(self, characteristic, data):
        try:
            status = parse_reply(data)
        except ValueError:
            return
        self.last_status = status
        future = self.pending.get(status['sequence'])
        if future and not future.done(): future.set_result(status)

    async def command(self, op, payload=b'', timeout=120):
        async with self.lock:
            if not self.client or not self.client.is_connected:
                raise ConnectionError('Connect Bluetooth first')
            self.sequence = self.sequence%65535+1
            seq = self.sequence
            future = asyncio.get_running_loop().create_future()
            self.pending[seq] = future
            try:
                await self.client.write_gatt_char(COMMAND, struct.pack('<HB',seq,op)+payload, response=True)
                status = await asyncio.wait_for(future,timeout)
                if status['op'] != op or status['code']:
                    raise RuntimeError(f"Device rejected op {op}: code {status['code']}, mode {status['mode']}")
                return status
            finally:
                self.pending.pop(seq,None)

    async def upload(self, data, progress=None):
        await self.command(16,begin_payload(data))
        try:
            # Write-with-response negotiated size, capped by the firmware queue packet.
            size = max(13,min(237,self.client.mtu_size-10))
            for payload in chunks(data,size):
                status = await self.command(17,payload)
                if progress: progress(status['received'],len(data))
            return await self.command(18)
        except BaseException:
            if self.client and self.client.is_connected:
                try: await self.command(19,timeout=5)
                except Exception: pass
            raise

    async def midi(self, raw):
        if not self.client or not self.client.is_connected:
            raise ConnectionError('Connect Bluetooth first')
        timestamp = int(time.monotonic()*1000)&0x1FFF
        packet = bytes([0x80|(timestamp>>7),0x80|(timestamp&127)])+bytes(raw)
        await self.client.write_gatt_char(MIDI_CHAR,packet,response=False)

    async def close(self):
        if self.client:
            await self.client.disconnect()
            self.client = None

async def run(args):
    if args.action=='scan':
        from bleak import BleakScanner
        devices=await BleakScanner.discover(timeout=10,return_adv=True)
        for device,adv in devices.values():
            if SERVICE in [u.lower() for u in adv.service_uuids]: print(device)
        return
    player=Player()
    try:
        device=await player.connect(args.address)
        print('Connected:',device)
        if args.action=='upload':
            data=prepare_song(args.file,args.volume,args.seconds,args.rate,args.brr_cache)
            last=[-1]
            def progress(done,total):
                percent=done*100//total
                if percent!=last[0]: print(f'{percent}% ({done}/{total})'); last[0]=percent
            await player.upload(data,progress)
            if args.play: await player.command(2)
        elif args.action=='midi-input':
            import mido
            await player.command(6)
            with mido.open_input(args.input) as port:
                print('MIDI input ready. Ctrl+C to stop.')
                while True:
                    for message in port.iter_pending():
                        if message.type in ('note_on','note_off','control_change','program_change','pitchwheel'):
                            await player.midi(message.bytes())
                    await asyncio.sleep(.002)
        elif args.action=='note':
            await player.command(6)
            try:
                await player.midi([0x90,args.note,100]); await asyncio.sleep(1)
            finally: await player.midi([0x80,args.note,0])
        else:
            ops={'status':1,'play':2,'stop':3,'mute':4,'master':5,'midi':6,'loop':8,'boot':9}
            payload=bytes([args.value]) if args.action in ('mute','master','loop','boot') else b''
            await player.command(ops[args.action],payload)
        print(json.dumps(player.last_status,ensure_ascii=False))
    finally:
        await player.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--address',help='Optional Bluetooth device address')
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('scan','status','play','stop','midi'): sub.add_parser(name)
    for name in ('mute','master','loop','boot'):
        q=sub.add_parser(name); q.add_argument('value',type=int,choices=range(128) if name=='master' else (0,1))
    q=sub.add_parser('upload'); q.add_argument('file',type=Path); q.add_argument('--volume',type=float,default=1); q.add_argument('--play',action='store_true')
    q.add_argument('--seconds',type=float,default=10,help='WAV: take the first N seconds')
    q.add_argument('--rate',type=int,default=8000,help='WAV: mono playback rate')
    q.add_argument('--brr-cache',type=Path,help='Optional already encoded WAV at --rate')
    q=sub.add_parser('note'); q.add_argument('--note',type=int,choices=range(128),default=60)
    q=sub.add_parser('midi-input'); q.add_argument('--input',required=True,help='mido input port name (requires python-rtmidi)')
    asyncio.run(run(p.parse_args()))

if __name__=='__main__': main()
