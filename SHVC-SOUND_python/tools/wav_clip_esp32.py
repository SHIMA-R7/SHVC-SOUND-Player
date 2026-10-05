"""Play a RAM-sized WAV clip on ESP32 SPC uploader; optional pre-encoded BRR."""
import argparse
from pathlib import Path
import struct
import sys
import wave
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from spc_play import SpcController
from midi2spc import brr

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('wav',type=Path)
p.add_argument('--port',default='COM16')
p.add_argument('--rate',type=int,default=8000)
p.add_argument('--seconds',type=float,default=10)
p.add_argument('--brr-cache',type=Path,help='BRR of this WAV already encoded at --rate')
p.add_argument('--no-play',action='store_true',help='Validate/encode the clip without opening a serial port')
a=p.parse_args()
if not 4000<=a.rate<=32000: raise ValueError('Rate must be 4000..32000')
if a.seconds<=0: raise ValueError('Seconds must be positive')
if a.brr_cache:
    data=bytearray(a.brr_cache.read_bytes())
else:
    with wave.open(str(a.wav)) as w:
        if w.getsampwidth()!=2 or w.getcomptype()!='NONE':
            raise ValueError('Only uncompressed 16-bit PCM WAV supported')
        rate=w.getframerate()
        samples=np.frombuffer(w.readframes(int(a.seconds*rate)),dtype='<i2').reshape(-1,w.getnchannels()).mean(axis=1)/32768
    count=int(len(samples)*a.rate/rate)
    if count==0: raise ValueError('Empty WAV clip')
    samples=np.interp(np.arange(count)*rate/a.rate,np.arange(len(samples)),samples)
    samples=samples/(np.max(np.abs(samples))+1e-9)*.8
    print('Encoding WAV to BRR...',flush=True)
    data=bytearray(brr.encode(samples,loop=False))
if not data or len(data)%9 or 0x400+len(data)>0xffc0:
    raise ValueError('BRR must fit RAM $0400-$FFBF and contain complete blocks')
if any(data[i]&1 for i in range(0,len(data)-9,9)):
    raise ValueError('Unexpected end flag inside BRR')
data[-9]=(data[-9]&0xfc)|1 # one shot, no loop
pitch=round(4096*a.rate/32000)
if not 1<=pitch<=0x3fff: raise ValueError('Invalid pitch')
duration=len(data)//9*16/a.rate

# Dedicated startup program, independent of SPC restore stub and its RAM overlap.
code=bytearray.fromhex('20 8F 99 F4') # CLRP; mark started
def dsp(reg,value): code.extend([0x8f,reg,0xf2,0x8f,value,0xf3])
dsp(0x6c,0x60) # mute; echo writes disabled
dsp(0x5c,0xff) # release all old voices
for reg in range(128):
    if reg not in (0x6c,0x5c): dsp(reg,0)
for reg,value in [(0x0c,80),(0x1c,80),(0x5d,3),
                  (0x00,96),(0x01,96),(0x02,pitch&255),(0x03,pitch>>8),
                  (0x04,0),(0x05,0),(0x07,0x7f),(0x5c,0),
                  (0x6c,0x20),(0x4c,1)]: dsp(reg,value)
code.extend([0x8f,0x98,0xf4,0x2f,0xfe]) # configured; idle forever
# Keep code away from directory $0300 and BRR $0400.
code_addr=0xffc0-len(code)
if 0x400+len(data)>code_addr:
    raise ValueError('Clip overlaps startup code: shorten the WAV')
directory=struct.pack('<HH',0x400,0x400)
print(f'WAV {a.wav.name}: {duration:.3f}s, {a.rate}Hz mono, BRR {len(data)} bytes',flush=True)
if a.no_play:
    print(f'Validated directory, pitch and startup code ({len(code)} bytes at ${code_addr:04X}); serial port unopened.',flush=True)
    sys.exit(0)
c=SpcController(a.port,log=lambda _:None)
success=False
sending=False
try:
    c.set_volume(0)
    c.reset()
    for addr,payload in [(0x400,data),(0x300,directory),(code_addr,code)]:
        c.set_address(addr,True)
        sending=True
        c.send_bytes(payload)
        sending=False
        print(f'Transferred {len(payload)} bytes at ${addr:04X}',flush=True)
    c.jump_to(code_addr)
    marker=c.wait_port(0,(0x98,),timeout=2)
    if marker!=0x98: raise RuntimeError(f'WAV setup not confirmed: {marker:02X}')
    print(f'PLAYING WAV CLIP, marker={marker:02X}, duration={duration:.3f}s',flush=True)
    success=True
finally:
    if not success:
        import time
        if sending:
            c.ser.timeout=.1
            until=time.monotonic()+6
            while time.monotonic()<until: c.ser.read(4096)
            c.ser.reset_input_buffer()
            c.ser.timeout=10
        try:
            c.set_volume(0)
            c.reset()
        finally:
            c.close()
    else:
        c.close()
