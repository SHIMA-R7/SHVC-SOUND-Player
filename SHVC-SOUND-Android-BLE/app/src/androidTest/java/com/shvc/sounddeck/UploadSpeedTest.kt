package com.shvc.sounddeck

import android.os.ParcelFileDescriptor
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

/** Opt-in hardware benchmark; music is read from the phone, never packaged. */
class UploadSpeedTest {
    @Test fun uploadAndPlay() = runBlocking {
        val args=InstrumentationRegistry.getArguments()
        val address=args.getString("deckAddress") ?: return@runBlocking
        val file=args.getString("spcPath") ?: error("spcPath required")
        require(file=="/data/local/tmp/shvc-benchmark.spc")
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val raw=ParcelFileDescriptor.AutoCloseInputStream(
            instrumentation.uiAutomation.executeShellCommand("cat $file")).use { it.readBytes() }
        val song=SongCodec.prepare("benchmark.spc",raw)
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        val deck=BleDeck(instrumentation.targetContext,scope,args.getString("window")?.toInt() ?: 8,args.getString("transport")!="nr")
        try {
            deck.connect(address)
            delay(1500)
            if(args.getString("faultTests")=="true") {
                if(deck.command(1).flags and 128!=0) {
                    val data=song.bytes.copyOfRange(0,501)
                    val crc=java.util.zip.CRC32().apply { update(data) }.value
                    deck.command(16,SongCodec.begin(song.bytes))
                    deck.sendUnacknowledged(21,SongCodec.u32(0)+SongCodec.u32(crc xor 1)+data)
                    assertEquals(2,deck.command(1,allowValidationError=true).code)
                    deck.command(22,SongCodec.u32(0))
                    deck.sendUnacknowledged(21,SongCodec.u32(501)+SongCodec.u32(crc)+data)
                    assertEquals(2,deck.command(1,allowValidationError=true).code)
                    deck.command(22,SongCodec.u32(0))
                    deck.sendUnacknowledged(21,SongCodec.u32(0)+SongCodec.u32(crc)+data)
                    assertEquals(501L,deck.command(1).received)
                    deck.command(19)
                }

                val interrupted=runCatching {
                    deck.upload(song.bytes) { _,_ -> error("benchmark interruption") }
                }
                assertTrue(interrupted.isFailure)
                assertEquals(1,deck.command(2).mode)
                val invalid=song.bytes.clone().also { it[0]=0 }
                assertTrue(runCatching { deck.upload(invalid) { _,_ -> } }.isFailure)
                assertEquals(1,deck.command(2).mode)
                val wrongCrc=SongCodec.begin(song.bytes).also { it[4]=(it[4].toInt() xor 1).toByte() }
                deck.command(16,wrongCrc)
                for(offset in song.bytes.indices step 237) {
                    val end=minOf(offset+237,song.bytes.size)
                    deck.command(17,SongCodec.u32(offset.toLong())+song.bytes.copyOfRange(offset,end))
                }
                assertTrue(runCatching { deck.command(18) }.isFailure)
                deck.command(19)
                assertEquals(1,deck.command(2).mode)
                android.util.Log.i("UploadSpeed","faultTests=passed")
            }
            repeat(args.getString("repeat")?.toInt() ?: 1) { run ->
            val started=SystemClock.elapsedRealtime()
            var previous=0
            deck.upload(song.bytes) { done,total ->
                assertTrue(done>=previous); assertEquals(song.bytes.size,total); previous=done
            }
            val elapsed=SystemClock.elapsedRealtime()-started
            assertEquals(song.bytes.size,previous)
            val info=deck.command(1)
            assertEquals(song.bytes.size.toLong(),info.received)
            assertEquals(0L,info.dropped)
            android.util.Log.i("UploadSpeed","run=$run bytes=${song.bytes.size} elapsedMs=$elapsed")
            val playStarted=SystemClock.elapsedRealtime()
            assertEquals(1,deck.command(2).mode)
            android.util.Log.i("UploadSpeed","run=$run playMs=${SystemClock.elapsedRealtime()-playStarted}")
            }
        } finally { deck.disconnect(); scope.cancel() }
    }
}
