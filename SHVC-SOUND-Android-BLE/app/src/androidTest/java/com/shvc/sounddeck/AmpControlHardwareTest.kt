package com.shvc.sounddeck

import android.os.ParcelFileDescriptor
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

/** Current external audio output is not attached to GPIO33: verify the PWM control state, not audible fading. */
class AmpControlHardwareTest {
    @Test fun profilesFadeAndRestoreWithoutChangingSongData() = runBlocking {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val address=InstrumentationRegistry.getArguments().getString("deckAddress") ?: return@runBlocking
        val raw=ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
            "cat /data/local/tmp/shvc-retry-test.spc")).use { it.readBytes() }
        val song=SongCodec.prepare("amp.spc",raw)
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        val deck=BleDeck(instrumentation.targetContext,scope)
        try {
            deck.connect(address)
            assertEquals(0,deck.command(15).ampProfile)
            deck.upload(song.bytes) { _,_ -> }; assertEquals(1,deck.command(2).mode)
            try { deck.command(14,SongCodec.u32(600)); fail("bypass fade accepted") }
            catch(e: DeviceCommandException) { assertEquals(1,e.code) }
            assertEquals(0L,deck.command(12,byteArrayOf(2)).received)
            try { deck.command(13,byteArrayOf(160.toByte())); fail("fixed amp volume accepted") }
            catch(e: DeviceCommandException) { assertEquals(1,e.code) }
            assertEquals(1,deck.command(12,byteArrayOf(1)).ampProfile)
            assertEquals(160L,deck.command(13,byteArrayOf(160.toByte())).received)
            deck.command(14,SongCodec.u32(1000))
            val duties=mutableListOf<Long>()
            repeat(12) { delay(100); val state=deck.command(15); assertEquals(1,state.mode); duties.add(state.received) }
            assertTrue(duties.first() in 1..159)
            assertTrue(duties.zipWithNext().all { (a,b)->a>=b })
            assertEquals(0L,duties.last())
            assertEquals(0,deck.command(15).volume and 1024)
            deck.command(2); assertEquals(160L,deck.command(15).received)
            assertEquals(0L,deck.command(12,byteArrayOf(0)).received)
            assertEquals(1,deck.command(1).mode)
            android.util.Log.i("AmpTest","duty=$duties profile0and2Disabled=true nextPlayRestores=true")
        } finally {
            withContext(NonCancellable) { runCatching { deck.command(12,byteArrayOf(0)) } }
            deck.disconnect(); scope.cancel()
        }
    }
}
