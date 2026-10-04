"""Offline wire-format and tempo-map regression tests; no BLE hardware required."""
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
import mido
from ble_song import prepare_song, chunks, begin_payload, parse_reply, REPLY

class SongTests(unittest.TestCase):
    def test_midi_tempo_and_running_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            song=mido.MidiFile(type=1,ticks_per_beat=480)
            tempo=mido.MidiTrack(); notes=mido.MidiTrack(); song.tracks.extend([tempo,notes])
            tempo.append(mido.MetaMessage('set_tempo',tempo=500000,time=0))
            tempo.append(mido.MetaMessage('set_tempo',tempo=1000000,time=480))
            notes.append(mido.Message('program_change',program=8,time=0))
            notes.append(mido.Message('note_on',note=60,velocity=100,time=480))
            notes.append(mido.Message('note_off',note=60,time=480))
            path=Path(folder)/'test.mid'; song.save(path)
            data=prepare_song(path)
            self.assertEqual(struct.unpack('<4sIII',data[:16]),(b'HTM1',3,1500,0))
            self.assertEqual([struct.unpack('<IBBBx',data[i:i+8])[0] for i in range(16,len(data),8)],[0,500,1500])
            self.assertEqual(data[20:23],bytes([0xC0,8,0]))

    def test_type2_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            song=mido.MidiFile(type=2); track=mido.MidiTrack(); song.tracks.append(track)
            track.append(mido.Message('note_on',note=60,time=0))
            path=Path(folder)/'test.mid'; song.save(path)
            with self.assertRaisesRegex(ValueError,'type 2'): prepare_song(path)

    def test_mtu23_offset_crc_roundtrip(self):
        data=bytes(range(256))*257
        result=bytearray()
        for packet in chunks(data):
            self.assertLessEqual(len(packet)+3,20)
            self.assertEqual(struct.unpack('<I',packet[:4])[0],len(result))
            result.extend(packet[4:])
        self.assertEqual(result,data)
        self.assertEqual(struct.unpack('<II',begin_payload(data)),(len(data),zlib.crc32(data)))

    def test_status_flags_and_errors(self):
        s=parse_reply(REPLY.pack(42,1,0,123,456,2,7,89,5))
        self.assertEqual(s['mode'],'MIDI live'); self.assertTrue(s['muted'] and s['loop'] and s['boot'])
        self.assertEqual(s['dropped'],5)
        with self.assertRaises(ValueError): parse_reply(b'bad')

if __name__=='__main__': unittest.main()
