"""Offline wire-format and tempo-map regression tests; no BLE hardware required."""
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
import wave
import argparse
import contextlib
import io
from unittest.mock import AsyncMock, patch
import mido
from ble_song import prepare_song, chunks, begin_payload, parse_reply, REPLY, spc_gain_payload

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

    def test_spc_gain_capability_and_legacy_status(self):
        self.assertIsNone(parse_reply(REPLY.pack(1,1,0,0,0,1,7,89,0))['spc_gain'])
        s=parse_reply(REPLY.pack(1,11,0,0,0,1,15,1024,0))
        self.assertEqual(s['spc_gain'],4); self.assertTrue(s['spc_gain_supported'])
        self.assertIsNone(parse_reply(REPLY.pack(1,1,0,0,0,2,15,127,0))['spc_gain'])
        self.assertEqual(spc_gain_payload(1.5),b'\x80\x01')
        for value in [-1,4.1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError): spc_gain_payload(value)

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

class PlayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_detect_connect(self):
        from ble_player import Player
        device=object()
        client=type('Client',(),{})()
        client.connect=AsyncMock(); client.start_notify=AsyncMock(); client.disconnect=AsyncMock()
        with patch('bleak.BleakScanner.find_device_by_filter',AsyncMock(return_value=device)) as scan, \
             patch('bleak.BleakClient',return_value=client):
            p=Player(); p.command=AsyncMock(return_value={})
            self.assertIs(await p.connect(),device)
            scan.assert_awaited_once(); p.command.assert_awaited_once_with(1)
            await p.close()

    async def test_spc_gain_cli_dispatch(self):
        import ble_player
        p=type('Client',(),{})()
        p.connect=AsyncMock(return_value='test device'); p.close=AsyncMock()
        p.command=AsyncMock(); p.last_status={'spc_gain_supported':True}
        with patch('ble_player.Player',return_value=p),contextlib.redirect_stdout(io.StringIO()):
            await ble_player.run(argparse.Namespace(action='spc-gain',address=None,value=2))
        p.command.assert_awaited_once_with(11,b'\x00\x02')

if __name__=='__main__': unittest.main()
