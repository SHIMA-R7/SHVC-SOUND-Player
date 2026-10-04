package com.shvc.sounddeck

import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

class WavBrrSourceTest {
    private fun wav(seconds: Int): ByteArray {
        val pcm=ByteArray(seconds*8000*2)
        val out=ByteArrayOutputStream()
        out.write("RIFF".toByteArray()); out.write(SongCodec.u32((36+pcm.size).toLong())); out.write("WAVEfmt ".toByteArray())
        out.write(SongCodec.u32(16)); out.write(SongCodec.u16(1)); out.write(SongCodec.u16(1))
        out.write(SongCodec.u32(8000)); out.write(SongCodec.u32(16000)); out.write(SongCodec.u16(2)); out.write(SongCodec.u16(16))
        out.write("data".toByteArray()); out.write(SongCodec.u32(pcm.size.toLong())); out.write(pcm)
        return out.toByteArray()
    }
    @Test fun convertsBeyondSoundRamWithoutReadingEntireFile() {
        val raw=wav(15); val input=ByteArrayInputStream(raw)
        val source=WavBrrSource(input)
        assertTrue(input.available()>raw.size-4097)
        assertEquals(15000L,source.durationMs)
        assertEquals(135000,source.totalBytes)
        var total=0
        while(true) {
            val chunk=source.nextChunk(504); if(chunk.isEmpty()) break
            assertEquals(0,chunk.size%9); assertTrue(chunk.size<=504)
            assertTrue(chunk.all { it==0.toByte() })
            total+=chunk.size
        }
        assertEquals(source.totalBytes,total)
    }
    @Test fun stereoKeepsChannelsSeparateAndUsesPairedBlocks() {
        val raw=wav(1)
        // Duplicate mono input into two independent encoder histories.
        val source=WavBrrSource(ByteArrayInputStream(raw),32000,2)
        assertEquals(36000,source.totalBytes)
        assertEquals(1000L,source.durationMs)
        val chunk=source.nextChunk(495)
        assertEquals(486,chunk.size)
        assertTrue(chunk.all { it==0.toByte() })
    }
    @Test fun stereoDoesNotMixRightAudioIntoLeft() {
        val out=ByteArrayOutputStream(); val pcm=ByteArrayOutputStream()
        repeat(64) { pcm.write(SongCodec.u16(0)); pcm.write(SongCodec.u16(12000)) }
        val data=pcm.toByteArray()
        out.write("RIFF".toByteArray()); out.write(SongCodec.u32((36+data.size).toLong())); out.write("WAVEfmt ".toByteArray())
        out.write(SongCodec.u32(16)); out.write(SongCodec.u16(1)); out.write(SongCodec.u16(2))
        out.write(SongCodec.u32(32000)); out.write(SongCodec.u32(128000)); out.write(SongCodec.u16(4)); out.write(SongCodec.u16(16))
        out.write("data".toByteArray()); out.write(SongCodec.u32(data.size.toLong())); out.write(data)
        val source=WavBrrSource(ByteArrayInputStream(out.toByteArray()),32000,2)
        val chunk=source.nextChunk(72)
        assertEquals(72,chunk.size)
        repeat(4) { block ->
            assertTrue(chunk.copyOfRange(block*18,block*18+9).all { it==0.toByte() })
            assertTrue(chunk.copyOfRange(block*18+9,block*18+18).any { it!=0.toByte() })
        }
    }
    @Test fun parsesSpcTextDurationWithoutGuessingMissingTags() {
        val raw=ByteArray(0x10180); raw[0x23]=0x1A
        "123".toByteArray().copyInto(raw,0xA9); "04500".toByteArray().copyInto(raw,0xAC)
        assertEquals(127500L,SongCodec.spcDuration(raw))
        raw[0x23]=0x1B; assertNull(SongCodec.spcDuration(raw))
        raw[0x23]=0x1A; raw.fill(0,0xA9,0xB1); assertNull(SongCodec.spcDuration(raw))
    }
    @Test(expected=java.io.EOFException::class) fun truncatedAudioIsRejected() {
        val raw=wav(1).copyOf(50); val source=WavBrrSource(ByteArrayInputStream(raw))
        source.nextChunk(504)
    }
}
