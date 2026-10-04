package com.shvc.sounddeck

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class TransferRetryTest {
    @Test fun retriesShvcFailureAndReturnsSuccess() = runBlocking {
        var runs=0; val retries=mutableListOf<Int>()
        val result=retryTransfer(recover={ n,_ -> retries.add(n) }) {
            if(++runs<3) throw DeviceCommandException(4,"SHVC")
            "played"
        }
        assertEquals("played",result); assertEquals(3,runs); assertEquals(listOf(2,3),retries)
    }
    @Test fun stopsAfterThreeAttempts() = runBlocking {
        var runs=0
        try { retryTransfer(recover={ _,_ -> }) { runs++; throw DeviceCommandException(2,"CRC") }; fail() }
        catch(e: DeviceCommandException) { assertEquals(2,e.code) }
        assertEquals(3,runs)
    }
    @Test fun doesNotRetryInvalidInputOrUnsupportedCommand() = runBlocking {
        for(error in listOf(IllegalArgumentException("file"),DeviceCommandException(1,"unsupported"))) {
            var runs=0
            try { retryTransfer(recover={ _,_ -> fail("retry") }) { runs++; throw error }; fail() }
            catch(e: Exception) { assertSame(error,e) }
            assertEquals(1,runs)
        }
    }
    @Test fun userCancellationDoesNotRetry() = runBlocking {
        var runs=0
        try { retryTransfer(recover={ _,_ -> fail("retry") }) { runs++; throw CancellationException("cancel") }; fail() }
        catch(e: CancellationException) { assertEquals("cancel",e.message) }
        assertEquals(1,runs)
    }
    @Test fun commandTimeoutCanRetryWhenParentIsActive() = runBlocking {
        var runs=0
        val result=retryTransfer(recover={ _,_ -> }) {
            if(++runs==1) withTimeout(1) { delay(1000) }
            42
        }
        assertEquals(42,result); assertEquals(2,runs)
    }
    @Test fun failedReconnectConsumesAnAttemptAndCanRecover() = runBlocking {
        var runs=0; val retries=mutableListOf<Int>()
        val result=retryTransfer(recover={ n,_ -> retries.add(n); if(n==2) throw IllegalStateException("connect") }) {
            if(++runs==1) throw IllegalStateException("disconnect")
            42
        }
        assertEquals(42,result); assertEquals(2,runs); assertEquals(listOf(2,3),retries)
    }
}
