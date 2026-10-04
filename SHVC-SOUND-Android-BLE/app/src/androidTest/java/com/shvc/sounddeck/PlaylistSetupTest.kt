package com.shvc.sounddeck

import android.net.Uri
import android.os.ParcelFileDescriptor
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.Assert.*
import java.io.File
import java.security.MessageDigest

/** Explicit ADB-only import utility; source songs are never bundled in the APK. */
class PlaylistSetupTest {
    @Test fun importsRequestedPlaylist() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val names=InstrumentationRegistry.getArguments().getString("playlistNamesBase64") ?: return
        val app=instrumentation.targetContext
        val titles=JSONArray(String(android.util.Base64.decode(names,android.util.Base64.DEFAULT),Charsets.UTF_8))
        require(titles.length() in 1..64)
        val prefs=app.getSharedPreferences("sound-deck",0)
        val existing=JSONArray(prefs.getString("library","[]"))
        val entries=JSONArray(); val queue=JSONArray(); val imported=mutableSetOf<String>()
        val directory=File(app.filesDir,"playlist-import").apply { mkdirs() }
        repeat(titles.length()) { index ->
            val raw=ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                "cat /data/local/tmp/shvc-playlist/$index.spc")).use { it.readBytes() }
            val song=SongCodec.prepare(titles.getString(index),raw)
            assertEquals("SPC",song.kind)
            assertNotNull(song.durationMs)
            val hash=MessageDigest.getInstance("SHA-256").digest(raw).joinToString("") { "%02x".format(it) }
            val file=File(directory,"$hash.spc").apply { writeBytes(raw) }
            val uri=Uri.fromFile(file).toString()
            queue.put(uri); imported.add(uri)
            entries.put(JSONObject().put("uri",uri).put("name",titles.getString(index)).put("kind","SPC"))
            android.util.Log.i("PlaylistSetup","index=$index title=${song.title} durationMs=${song.durationMs}")
        }
        repeat(existing.length()) { index ->
            val entry=existing.getJSONObject(index)
            if(entry.getString("uri") !in imported) entries.put(entry)
        }
        assertTrue(prefs.edit().putString("library",entries.toString()).putString("playlist",queue.toString())
            .putBoolean("playlist-tags",true).putBoolean("playlist-repeat",false).commit())
        assertEquals(titles.length(),JSONArray(prefs.getString("playlist","[]")).length())
    }
}
