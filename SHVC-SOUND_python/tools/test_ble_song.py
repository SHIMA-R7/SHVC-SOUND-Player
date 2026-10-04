"""Offline wire-format and tempo-map regression tests; no BLE hardware required."""
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
import wave
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

    def test_wav_bundle_layout_and_one_shot(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'clip.wav'
            with wave.open(str(path),'wb') as w:
                w.setnchannels(2); w.setsampwidth(2); w.setframerate(8000)
                w.writeframes(struct.pack('<hh',1000,-1000)*32)
            data=prepare_song(path,wav_seconds=.004)
            magic,addr,length,signal,ports=struct.unpack('<4sHHB4s3x',data[:16])
            self.assertEqual((magic,signal,ports),(b'HSP1',0x5A,b'\0'*4))
            self.assertEqual(addr+length,0xFFC0)
            self.assertEqual(len(data),16+65536+length)
            self.assertEqual(data[16+0x300:16+0x304],struct.pack('<HH',0x400,0x400))
            self.assertEqual(data[16+0x400]&1,0)
            self.assertEqual(data[16+0x409]&3,1)
            self.assertIn(bytes([0x78,0x5A,0xF4]),data[16+65536:])

    def test_wav_rejects_non16bit_and_overflow(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.wav'
            with wave.open(str(path),'wb') as w:
                w.setnchannels(1); w.setsampwidth(1); w.setframerate(8000); w.writeframes(b'\x80'*100)
            with self.assertRaisesRegex(ValueError,'16-bit'): prepare_song(path)
            with wave.open(str(path),'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b'\0\0'*120000)
            with self.assertRaisesRegex(ValueError,'too long'): prepare_song(path,wav_seconds=15)

if __name__=='__main__': unittest.main()
