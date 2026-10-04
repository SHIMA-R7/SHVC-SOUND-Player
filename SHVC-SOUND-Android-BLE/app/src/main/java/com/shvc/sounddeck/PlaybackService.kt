package com.shvc.sounddeck

import android.app.*
import android.content.Intent
import android.os.*

/** Keeps connected playback running when the phone screen turns off. */
class PlaybackService: Service() {
    private var wake: PowerManager.WakeLock?=null
    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("playback","連続再生",NotificationManager.IMPORTANCE_LOW))
        val open=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
        startForeground(7,Notification.Builder(this,"playback")
            .setSmallIcon(R.drawable.ic_deck).setContentTitle("SHVC Sound Deck")
            .setContentText("音源へ接続して連続再生中").setOngoing(true).setContentIntent(open).build())
        wake=(getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,"SoundDeck:Playback").also { it.acquire() }
    }
    override fun onStartCommand(intent: Intent?,flags: Int,startId: Int)=START_NOT_STICKY
    override fun onBind(intent: Intent?)=null
    override fun onDestroy() { wake?.let { if(it.isHeld) it.release() }; wake=null; super.onDestroy() }
}
