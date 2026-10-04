"""Versioned BLE wire format and SPC / Standard MIDI File preparation."""
from pathlib import Path
import struct
import sys
import zlib

SERVICE = '89e30000-3c3b-4df7-a74a-25fdd879b40c'
COMMAND = '89e30001-3c3b-4df7-a74a-25fdd879b40c'
STATUS = '89e30002-3c3b-4df7-a74a-25fdd879b40c'
MIDI_CHAR = '7772e5db-3868-4112-a1a9-f2669d106bf3'
MODES = ['stopped', 'SPC', 'MIDI live', 'MIDI file', 'loading', 'error']
MAX_FILE = 256000
REPLY = struct.Struct('<HBBIIBBHI')

def parse_reply(data):
    if len(data) != REPLY.size:
        raise ValueError('Invalid BLE reply length')
    seq, op, code, received, total, mode, muted, master, dropped = REPLY.unpack(data)
    spc_gain = master / 256 if muted&8 and (mode==1 or op==11) else None
    return dict(sequence=seq, op=op, code=code, received=received, total=total,
                mode=MODES[mode] if mode < len(MODES) else 'unknown',
                muted=bool(muted&1), loop=bool(muted&2), boot=bool(muted&4), master=master, dropped=dropped,
                spc_gain=spc_gain, spc_gain_supported=bool(muted&8))

def spc_gain_payload(gain):
    if not 0 <= gain <= 4:
        raise ValueError('SPC gain must be between 0 and 4')
    return struct.pack('<H',round(gain*256))

def prepare_wav(path, volume=1.0, seconds=10, rate=8000, brr_cache=None):
    """Build a self-contained one-shot BRR player using the existing HSP1 loader."""
    import wave
    import numpy as np
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from midi2spc import brr
    if not 4000<=rate<=32000 or not 0<seconds<=60 or not 0<=volume<=1:
        raise ValueError('WAV: rate 4000..32000, seconds 0..60, volume 0..1')
    if brr_cache:
        data=bytearray(Path(brr_cache).read_bytes())
    else:
        with wave.open(str(path)) as w:
            if w.getsampwidth()!=2 or w.getcomptype()!='NONE':
                raise ValueError('WAV must be uncompressed 16-bit PCM')
            source_rate=w.getframerate()
            samples=np.frombuffer(w.readframes(int(seconds*source_rate)),dtype='<i2').reshape(-1,w.getnchannels()).mean(axis=1)/32768
        count=int(len(samples)*rate/source_rate)
        if not count: raise ValueError('Empty WAV')
        if (count+15)//16*9>63500: raise ValueError('WAV too long for SHVC RAM; shorten the clip or lower its rate')
        samples=np.interp(np.arange(count)*source_rate/rate,np.arange(len(samples)),samples)
        samples=samples/(np.max(np.abs(samples))+1e-9)*.8
        data=bytearray(brr.encode(samples,loop=False))
    if not data or len(data)%9 or any(data[i]&1 for i in range(0,len(data)-9,9)):
        raise ValueError('Invalid BRR clip')
    data[-9]=(data[-9]&0xFC)|1
    pitch=round(4096*rate/32000)
    code=bytearray.fromhex('20 8F 99 F4')
    def dsp(reg,value): code.extend([0x8F,reg,0xF2,0x8F,value,0xF3])
    dsp(0x6C,0x60); dsp(0x5C,0xFF)
    for reg in range(128):
        if reg not in (0x6C,0x5C): dsp(reg,0)
    for reg,value in [(0x0C,round(80*volume)),(0x1C,round(80*volume)),(0x5D,3),
                      (0,96),(1,96),(2,pitch&255),(3,pitch>>8),(4,0),(5,0),(7,127),(0x5C,0)]: dsp(reg,value)
    # Same two-stage handshake as an SPC snapshot; start audio only after host release.
    code.extend([0x78,0x5A,0xF4,0xD0,0xFB,0x8F,0x98,0xF4,0x78,0,0xF4,0xD0,0xFB])
    dsp(0x6C,0x20); dsp(0x4C,1); code.extend([0x2F,0xFE])
    addr=0xFFC0-len(code)
    if 0x400+len(data)>addr: raise ValueError('WAV overlaps startup code; shorten the clip')
    ram=bytearray(65536)
    ram[0x300:0x304]=struct.pack('<HH',0x400,0x400)
    ram[0x400:0x400+len(data)]=data
    return struct.pack('<4sHHB4s3x',b'HSP1',addr,len(code),0x5A,b'\0'*4)+ram+code

def prepare_song(path, volume=1.0, wav_seconds=10, wav_rate=8000, brr_cache=None):
    path = Path(path)
    if not 0 <= volume <= 1:
        raise ValueError('SPC volume must be between 0 and 1')
    if path.suffix.lower() == '.spc':
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from spc_play import SpcFile, build_final_stub, handshake_values
        s = SpcFile(path)
        stub = build_final_stub(s, volume_factor=volume, port_handshake=True)
        signal, _ = handshake_values(s)
        result = (struct.pack('<4sHHB4s3x', b'HSP1', 0xFFC0-len(stub), len(stub),
                              signal, bytes(s.ram[0xF4:0xF8])) + bytes(s.ram) + stub)
    elif path.suffix.lower()=='.wav':
        result=prepare_wav(path,volume,wav_seconds,wav_rate,brr_cache)
    elif path.suffix.lower() in ('.mid', '.midi'):
        import mido
        song = mido.MidiFile(path)
        if song.type == 2:
            raise ValueError('Asynchronous MIDI type 2 is unsupported')
        elapsed = 0.0
        events = []
        supported = {'note_on', 'note_off', 'control_change', 'program_change', 'pitchwheel'}
        for message in song:  # mido merges tracks and applies the tempo map
            elapsed += message.time
            if message.type in supported:
                raw = message.bytes()
                events.append(struct.pack('<IBBBx', round(elapsed*1000),
                                          raw[0], raw[1], raw[2] if len(raw)>2 else 0))
        if not events or len(events)>30000 or elapsed>86400:
            raise ValueError('MIDI must contain 1..30000 supported events and be <=24 hours')
        result = struct.pack('<4sIII', b'HTM1', len(events), round(elapsed*1000), 0)+b''.join(events)
    else:
        raise ValueError('Select an SPC, MIDI or 16-bit PCM WAV file')
    if len(result)>MAX_FILE:
        raise ValueError('Song exceeds the 256000-byte storage limit')
    return result

def chunks(data, payload_size=13):
    # 3-byte command header + 4-byte offset + 13-byte payload fits MTU 23.
    for offset in range(0, len(data), payload_size):
        yield struct.pack('<I', offset)+data[offset:offset+payload_size]

def begin_payload(data):
    return struct.pack('<II', len(data), zlib.crc32(data))
