package com.shvc.sounddeck

import android.os.ParcelFileDescriptor
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

/** Opt-in: reject a bad upload, then retransfer the real song and verify SHVC playback. */
class TransferRetryHardwareTest {
    @Test fun rejectedUploadAutomaticallyRetriesAndPlays() = runBlocking {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val address=InstrumentationRegistry.getArguments().getString("deckAddress") ?: return@runBlocking
        val raw=ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
            "cat /data/local/tmp/shvc-retry-test.spc")).use { it.readBytes() }
        val song=SongCodec.prepare("retry.spc",raw)
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        val deck=BleDeck(instrumentation.targetContext,scope)
        var runs=0; val retries=mutableListOf<Int>()
        try {
            deck.connect(address)
            val status=retryTransfer(recover={ n,error ->
                assertTrue(error is DeviceCommandException)
                assertEquals(2,(error as DeviceCommandException).code)
                retries.add(n); deck.command(19)
            }) {
                runs++
                val data=if(runs==1) song.bytes.clone().also { it[0]=0 } else song.bytes
                deck.upload(data) { _,_ -> }
                deck.command(2)
            }
            assertEquals(2,runs); assertEquals(listOf(2),retries)
            assertEquals(1,status.mode); assertEquals(0,status.code)
            assertEquals(0L,status.dropped)
            android.util.Log.i("RetryTest","title=${song.title} attempts=$runs rejectedUploadRecovered=true")
        } finally { deck.disconnect(); scope.cancel() }
    }
}
