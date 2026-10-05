package com.shvc.sounddeck

import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

/** Explicit opt-in hardware test: pass -e deckAddress <BLE address>. */
class RealDeckTest {
    @Test fun commandsAndMidiWithRealFirmware() = runBlocking {
        val address=InstrumentationRegistry.getArguments().getString("deckAddress") ?: return@runBlocking
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
        val deck=BleDeck(context,scope)
        var original: DeviceStatus?=null
        try {
            deck.connect(address)
            original=deck.command(1)
            assertTrue(deck.link.value.ready)
            deck.command(4,byteArrayOf(if(original.muted) 0 else 1))
            assertEquals(!original.muted,deck.status.value!!.muted)
            deck.command(4,byteArrayOf(if(original.muted) 1 else 0))
            deck.command(6)
            assertEquals(2,deck.status.value!!.mode)
            for(note in intArrayOf(60,64,67)) {
                deck.midi(byteArrayOf(0x90.toByte(),note.toByte(),80))
                delay(250)
                deck.midi(byteArrayOf(0x80.toByte(),note.toByte(),0))
            }
        } finally {
            if(deck.link.value.ready && original!=null) {
                deck.command(4,byteArrayOf(if(original.muted) 1 else 0))
                if(original.mode==1 || original.mode==3) deck.command(2) else deck.command(3)
            }
            deck.disconnect(); scope.cancel()
        }
    }
}
