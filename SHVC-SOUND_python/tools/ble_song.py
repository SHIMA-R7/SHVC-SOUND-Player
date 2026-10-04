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
    return dict(sequence=seq, op=op, code=code, received=received, total=total,
                mode=MODES[mode] if mode < len(MODES) else 'unknown',
                muted=bool(muted&1), loop=bool(muted&2), boot=bool(muted&4), master=master, dropped=dropped)

def prepare_song(path, volume=1.0):
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
        raise ValueError('Select an SPC or MIDI file')
    if len(result)>MAX_FILE:
        raise ValueError('Song exceeds the 256000-byte storage limit')
    return result

def chunks(data, payload_size=13):
    # 3-byte command header + 4-byte offset + 13-byte payload fits MTU 23.
    for offset in range(0, len(data), payload_size):
        yield struct.pack('<I', offset)+data[offset:offset+payload_size]

def begin_payload(data):
    return struct.pack('<II', len(data), zlib.crc32(data))
