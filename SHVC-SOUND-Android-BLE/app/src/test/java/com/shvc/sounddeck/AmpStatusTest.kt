package com.shvc.sounddeck

import org.junit.Assert.*
import org.junit.Test

class AmpStatusTest {
    @Test fun ampReplyDoesNotBecomeSpcGain() {
        val state=DeviceStatus(1,15,0,120,500,1,8,160 or 256 or 1024,0)
        assertEquals(1,state.ampProfile); assertEquals(160,state.ampLevel); assertNull(state.gain)
        assertNull(state.copy(op=1).ampProfile)
        assertEquals(1f,state.copy(op=11,volume=256).gain)
    }
    @Test fun keepsFadeTimeSeparateFromTotalDuration() {
        val data=ByteArray(0xB1); data[0x23]=0x1A
        "079".toByteArray().copyInto(data,0xA9)
        "08000".toByteArray().copyInto(data,0xAC)
        assertEquals(87000L,SongCodec.spcDuration(data)); assertEquals(8000L,SongCodec.spcFade(data))
        data[0x23]=0x1B; assertNull(SongCodec.spcDuration(data)); assertEquals(0L,SongCodec.spcFade(data))
    }
}
