package com.shvc.sounddeck

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive

/** Retry transport/device failures; never retry invalid local input or user cancellation. */
internal suspend fun <T> retryTransfer(
    attempts: Int=3,
    recover: suspend (Int,Throwable)->Unit,
    transfer: suspend ()->T
): T {
    require(attempts>0)
    var previous: Exception?=null
    for(attempt in 1..attempts) {
        try {
            previous?.let { recover(attempt,it) }
            return transfer()
        }
        catch(e: Exception) {
            currentCoroutineContext().ensureActive()
            if(e is CancellationException && e !is TimeoutCancellationException) throw e
            val retryable=e is TimeoutCancellationException ||
                (e is DeviceCommandException && e.code in 2..4) ||
                (e is IllegalStateException && e !is DeviceCommandException)
            if(!retryable || attempt==attempts) throw e
            previous=e
        }
    }
    error("Unreachable")
}
