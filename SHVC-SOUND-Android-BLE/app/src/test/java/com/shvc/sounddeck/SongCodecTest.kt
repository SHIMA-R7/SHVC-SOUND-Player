package com.shvc.sounddeck

import org.junit.Assert.*
import org.junit.Test
import java.security.MessageDigest

class SongCodecTest {
    private fun hex(s: String) = s.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    private fun sha(b: ByteArray) = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it.toInt() and 255) }
    @Test fun spcMatchesEstablishedPlayer() {
        val data=ByteArray(0x10180)
        "SNES-SPC700 Sound File Data".toByteArray().copyInto(data)
        data[0x23]=0x1A
        byteArrayOf(0x62,8,7,11,13,2,0xEF.toByte()).copyInto(data,0x25)
        "Fixture".toByteArray().copyInto(data,0x2E)
        "TEST".toByteArray().copyInto(data,0x4E)
        repeat(65536) { data[0x100+it]=(it*37+11).toByte() }
        repeat(128) { data[0x10100+it]=(it*3+5).toByte() }
        val song=SongCodec.prepare("fixture.spc",data)
        assertEquals("Fixture",song.title)
        assertEquals(66376,song.bytes.size)
        assertEquals("13c3a3b077a0b0246d66ee05beaaa06d5c9e2b61cdfb8dabc7809fa5abc390c9",sha(song.bytes))
    }
    @Test fun midiTempoTracksMatchEstablishedPlayer() {
        val input=hex("4d546864000000060001000201e04d54726b0000001300ff510307a1208360ff51030f424000ff2f004d54726b0000001100c0088360903c648360803c4000ff2f00")
        assertArrayEquals(hex("48544d3103000000dc0500000000000000000000c0080000f4010000903c6400dc050000803c4000"),SongCodec.prepare("fixture.mid",input).bytes)
    }
    @Test fun wavBrrMatchesEstablishedPlayer() {
        val input=hex("524946466400000057415645666d74201000000001000100401f0000803e0000020010006461746140000000" + "e803".repeat(32))
        val output=SongCodec.prepare("fixture.wav",input).bytes
        assertEquals(66417,output.size)
        assertEquals("8460df5ba180d83459d1fa3d00c8d379c262824513a25a01e86b72c7d37e01d1",sha(output))
    }
    @Test fun statusUsesNegotiatedGain() {
        val raw=ByteArray(20); raw[12]=1; raw[13]=8; raw[15]=4
        assertEquals(4f,DeviceStatus.parse(raw).gain!!,0f)
        raw[13]=0
        assertNull(DeviceStatus.parse(raw).gain)
    }
    @Test fun chipProgressRequiresLoadingAndCapability() {
        val s=DeviceStatus(0,0,0,32768,65536,4,16,89,0)
        assertEquals(0.5f,s.loadProgress!!,0f)
        assertNull(s.copy(mode=1).loadProgress)
        assertNull(s.copy(flags=0).loadProgress)
        assertNull(s.copy(total=0).loadProgress)
    }
    @Test(expected=IllegalArgumentException::class) fun rejectsTruncatedSpc() { SongCodec.prepare("bad.spc",ByteArray(20)) }
    @Test fun beginCarriesCrcAndLength() { assertArrayEquals(hex("090000002639f4cb"),SongCodec.begin("123456789".toByteArray())) }
}
