package com.shvc.sounddeck

import android.os.ParcelFileDescriptor
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class WavStreamTest {
    @Test fun streamsAcrossMultipleRingWraps() = runBlocking {
        val args=InstrumentationRegistry.getArguments()
        val address=args.getString("deckAddress") ?: return@runBlocking
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        val deck=BleDeck(instrumentation.targetContext,scope)
        try {
            deck.connect(address)
            ParcelFileDescriptor.AutoCloseInputStream(
                instrumentation.uiAutomation.executeShellCommand("cat /data/local/tmp/shvc-stream-test.wav")).use { input ->
                val source=WavBrrSource(input,args.getString("rate")?.toInt() ?: 16000,args.getString("channels")?.toInt() ?: 1)
                assertTrue(source.durationMs>10000)
                assertTrue(source.totalBytes>62208*3)
                var elapsed=0L; var reported=0L
                deck.streamWav(source) { done,total ->
                    assertTrue(done>=elapsed); assertEquals(source.durationMs,total); elapsed=done
                    if(done-reported>=5000) { android.util.Log.i("WavStream","playedMs=$done totalMs=$total"); reported=done }
                }
                assertEquals(source.durationMs,elapsed)
                val status=deck.command(1)
                assertEquals(source.totalBytes.toLong(),status.received)
                assertEquals(0,status.mode); assertEquals(0L,status.dropped)
                android.util.Log.i("WavStream","complete bytes=${source.totalBytes} durationMs=${source.durationMs}")
            }
        } finally {
            if(deck.link.value.ready) deck.command(2)
            deck.disconnect(); scope.cancel()
        }
    }
}
