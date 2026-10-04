package com.shvc.sounddeck

import android.net.Uri
import android.os.ParcelFileDescriptor
import android.app.Application
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class TransferRetryUiTest {
    @Test fun retryButtonResumesFailedTrackAndFollowingTrack() = runBlocking {
        val args=InstrumentationRegistry.getArguments()
        val address=args.getString("deckAddress") ?: return@runBlocking
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val app=instrumentation.targetContext
        val prefs=app.getSharedPreferences("sound-deck",0)
        val previous=prefs.all
        val raw=ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
            "cat /data/local/tmp/shvc-retry-test.spc")).use { it.readBytes() }
        val files=listOf("Retry One","Retry Two","Retry Three").map { title ->
            File(app.cacheDir,"$title.spc").also { file ->
                val data=raw.clone(); data.fill(0,0x2E,0x4E); title.toByteArray().copyInto(data,0x2E)
                file.writeBytes(data)
            }
        }
        val goodSecond=files[1].readBytes(); files[1].writeBytes(byteArrayOf(0))
        val entries=JSONArray(); val queue=JSONArray()
        files.forEach { file ->
            val uri=Uri.fromFile(file).toString(); queue.put(uri)
            entries.put(JSONObject().put("uri",uri).put("name",file.name).put("kind","SPC"))
        }
        prefs.edit().putString("library",entries.toString()).putString("playlist",queue.toString())
            .putBoolean("playlist-tags",false).putInt("playlist-seconds",2).putBoolean("playlist-repeat",false).commit()
        val scenario=ActivityScenario.launch(MainActivity::class.java)
        val model=DeckViewModel(app.applicationContext as Application)
        try {
            model.ble.connect(address)
            withContext(Dispatchers.Main) { model.startPlaylist() }
            scenario.moveToState(Lifecycle.State.CREATED)
            withTimeout(45000) {
                while(model.ui.value.retryName==null || model.ui.value.playlistActive) delay(50)
            }
            assertEquals(1,model.ui.value.playlistIndex)
            assertEquals("Retry Two.spc",model.ui.value.retryName)
            files[1].writeBytes(goodSecond)
            withContext(Dispatchers.Main) { model.retryFailedTransfer() }
            val seen=mutableSetOf<String>()
            withTimeout(45000) {
                while(!model.ui.value.playlistActive) delay(20)
                while(model.ui.value.playlistActive) {
                    model.ui.value.playing?.title?.takeIf { !model.ui.value.busy }?.let { seen.add(it) }
                    delay(20)
                }
            }
            assertNull(model.ui.value.error); assertNull(model.ui.value.retryName)
            assertEquals(setOf("Retry Two","Retry Three"),seen)
            assertEquals(0,model.ble.command(1).mode)
            android.util.Log.i("RetryTest","retryAction=true resumedIndex=1 followingTrack=true")
        } finally {
            model.disconnect(); scenario.close()
            val editor=prefs.edit().clear()
            previous.forEach { (key,value) -> when(value) {
                is String -> editor.putString(key,value)
                is Boolean -> editor.putBoolean(key,value)
                is Int -> editor.putInt(key,value)
                is Long -> editor.putLong(key,value)
                is Float -> editor.putFloat(key,value)
            } }
            editor.commit(); files.forEach { it.delete() }
        }
    }
}
