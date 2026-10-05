package com.shvc.sounddeck

import android.app.Application
import android.net.Uri
import android.os.ParcelFileDescriptor
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class PlaylistTest {
    @Test fun switchesTracksWhileActivityIsInBackground() = runBlocking {
        val args=InstrumentationRegistry.getArguments()
        val address=args.getString("deckAddress") ?: return@runBlocking
        val checkFade=args.getString("ampFade")=="true"
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val app=instrumentation.targetContext.applicationContext as Application
        val prefs=app.getSharedPreferences("sound-deck",0)
        val previous=prefs.all
        val raw=ParcelFileDescriptor.AutoCloseInputStream(
            instrumentation.uiAutomation.executeShellCommand("cat /data/local/tmp/shvc-benchmark.spc")).use { it.readBytes() }
        val files=listOf("Playlist One","Playlist Two").mapIndexed { index,title ->
            File(app.cacheDir,"playlist-test-$index.spc").also { file ->
                val data=raw.clone(); data.fill(0,0x2E,0x4E); title.toByteArray().copyInto(data,0x2E); file.writeBytes(data)
            }
        }
        val entries=JSONArray(); val queue=JSONArray()
        files.forEach { file ->
            val uri=Uri.fromFile(file).toString(); queue.put(uri)
            entries.put(JSONObject().put("uri",uri).put("name",file.name).put("kind","SPC"))
        }
        prefs.edit().putString("library",entries.toString()).putString("playlist",queue.toString())
            .putBoolean("playlist-fade",true).putBoolean("playlist-tags",false).putInt("playlist-seconds",1).putBoolean("playlist-repeat",false).commit()
        val scenario=ActivityScenario.launch(MainActivity::class.java)
        val model=DeckViewModel(app)
        try {
            model.ble.connect(address)
            if(checkFade) { model.ble.command(12,byteArrayOf(1)); model.ble.command(13,byteArrayOf(160.toByte())) }
            withContext(Dispatchers.Main) { model.startPlaylist() }
            val seen=mutableSetOf<String>(); val fades=mutableSetOf<String>(); var background=false
            withTimeout(60000) {
                while(!model.ui.value.playlistActive) delay(20)
                while(model.ui.value.playlistActive) {
                    model.ui.value.playing?.title?.let { title ->
                        seen.add(title)
                        if(model.ble.status.value?.op==14 && (model.ble.status.value!!.volume and 1024)!=0) fades.add(title)
                    }
                    if(!background && seen.contains("Playlist One")) {
                        scenario.moveToState(Lifecycle.State.CREATED); background=true
                    }
                    delay(50)
                }
            }
            assertNull(model.ui.value.error)
            assertEquals(setOf("Playlist One","Playlist Two"),seen)
            assertEquals(0,model.ble.command(1).mode)
            if(checkFade) assertEquals(setOf("Playlist One","Playlist Two"),fades)
            android.util.Log.i("PlaylistTest","orderedTracks=2 backgroundPlayback=passed ampFades=$fades")
        } finally {
            if(checkFade) withContext(NonCancellable) { runCatching { model.ble.command(12,byteArrayOf(0)) } }
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
