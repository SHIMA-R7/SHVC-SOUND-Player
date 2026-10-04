package com.shvc.sounddeck

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream

data class LibrarySong(val uri: String,val name: String,val kind: String)
data class DeckUi(val busy: Boolean=false,val stage: String="",val progress: Float?=null,
    val error: String?=null,val retryName: String?=null,val library: List<LibrarySong> = emptyList(),val selected: String?=null,
    val playing: PreparedSong?=null,val cancellable: Boolean=false,
    val playlist: List<String> = emptyList(),val playlistActive: Boolean=false,
    val playlistIndex: Int=0,val remainingSeconds: Int=0,val fallbackSeconds: Int=120,
    val ampSupported: Boolean=false,val ampProfile: Int=0,val ampLevel: Int=160,val fadeEnabled: Boolean=true,
    val useTimeTags: Boolean=true,val playlistRepeat: Boolean=false,val streaming: Boolean=false,val wavRate: Int=16000,val wavChannels: Int=1)

class DeckViewModel(application: Application): AndroidViewModel(application) {
    val ble=BleDeck(application,viewModelScope)
    private val prefs=application.getSharedPreferences("sound-deck",0)
    private val mutableUi=MutableStateFlow(DeckUi())
    val ui=mutableUi.asStateFlow()
    private var action: Job?=null
    private var playlistJob: Job?=null
    private data class FailedTransfer(val entry: LibrarySong,val queue: List<LibrarySong>?,val index: Int)
    private var failedTransfer: FailedTransfer?=null
    private fun rememberFailure(entry: LibrarySong,queue: List<LibrarySong>?=null,index: Int=0) {
        failedTransfer=FailedTransfer(entry,queue,index)
        mutableUi.value=mutableUi.value.copy(retryName=entry.name)
    }
    private fun clearTransferFailure() {
        failedTransfer=null; mutableUi.value=mutableUi.value.copy(retryName=null)
    }
    fun retryFailedTransfer() {
        if(mutableUi.value.busy || mutableUi.value.playlistActive) return
        val failed=failedTransfer ?: return
        if(failed.queue!=null) startPlaylist(failed.index,failed.queue)
        else launchAction("曲を再転送中",true) { transferEntry(failed.entry) }
    }
    private val notes=mutableSetOf<Pair<Int,Int>>()
    init {
        val saved=runCatching {
            val array=JSONArray(prefs.getString("library","[]"))
            (0 until array.length()).map { val o=array.getJSONObject(it); LibrarySong(o.getString("uri"),o.getString("name"),o.getString("kind")) }
        }.getOrDefault(emptyList())
        val queue=runCatching { val a=JSONArray(prefs.getString("playlist","[]"));
            (0 until a.length()).map { a.getString(it) }.filter { uri -> saved.any { it.uri==uri } } }.getOrDefault(emptyList())
        mutableUi.value=DeckUi(library=saved,selected=saved.firstOrNull()?.uri,playlist=queue,
            fallbackSeconds=prefs.getInt("playlist-seconds",120),useTimeTags=prefs.getBoolean("playlist-tags",true),
            playlistRepeat=prefs.getBoolean("playlist-repeat",false),
            fadeEnabled=prefs.getBoolean("playlist-fade",true),
            wavRate=prefs.getInt("wav-rate",16000).takeIf { it in listOf(16000,32000) } ?: 16000,
            wavChannels=prefs.getInt("wav-channels",1).takeIf { it in 1..2 } ?: 1)
        viewModelScope.launch {
            ble.status.collect { status ->
                status?.ampProfile?.let { profile ->
                    mutableUi.value=mutableUi.value.copy(ampSupported=true,ampProfile=profile,ampLevel=status.ampLevel ?: 160)
                }
                if(mutableUi.value.busy && status?.mode==4) {
                    mutableUi.value=mutableUi.value.copy(stage="SHVC-SOUNDへ転送中",progress=status.loadProgress,cancellable=false)
                }
            }
        }
    }
    fun clearError() { mutableUi.value=mutableUi.value.copy(error=null) }
    fun report(message: String) { mutableUi.value=mutableUi.value.copy(error=message) }
    private fun launchAction(stage: String,cancellable: Boolean=false,block: suspend ()->Unit) {
        if(mutableUi.value.busy) return
        mutableUi.value=mutableUi.value.copy(busy=true,stage=stage,error=null,cancellable=cancellable,progress=null)
        action=viewModelScope.launch {
            try { block() }
            catch(e: TimeoutCancellationException) { mutableUi.value=mutableUi.value.copy(error="音源の応答がタイムアウトしました。再転送でやり直せます") }
            catch(e: CancellationException) { mutableUi.value=mutableUi.value.copy(error="転送を中止しました。前の保存曲は維持されています") }
            catch(e: Throwable) { mutableUi.value=mutableUi.value.copy(error=e.message ?: "操作に失敗しました") }
            finally { mutableUi.value=mutableUi.value.copy(busy=false,stage="",progress=null,cancellable=false) }
        }
    }
    fun scan() { runCatching { ble.scan() }.onFailure { report(it.message ?: "検索できません") } }
    fun connect(address: String) = launchAction("音源に接続中") {
        mutableUi.value=mutableUi.value.copy(playing=null)
        ble.connect(address); readAmpState()
    }
    private suspend fun readAmpState() {
        try {
            val status=ble.command(15)
            mutableUi.value=mutableUi.value.copy(ampSupported=true,ampProfile=status.ampProfile ?: 0,ampLevel=status.ampLevel ?: 160)
        } catch(e: DeviceCommandException) {
            if(e.code!=1) throw e
            mutableUi.value=mutableUi.value.copy(ampSupported=false,ampProfile=0)
        }
    }
    fun ampProfile(profile: Int) = launchAction("アンプ設定を変更中") {
        require(profile in 0..2)
        ble.command(12,byteArrayOf(profile.toByte())); readAmpState()
    }
    fun ampLevel(level: Int) = launchAction("アンプ音量を変更中") {
        require(level in 0..255)
        ble.command(13,byteArrayOf(level.toByte())); readAmpState()
    }
    fun playlistFade(enabled: Boolean) {
        mutableUi.value=mutableUi.value.copy(fadeEnabled=enabled)
        prefs.edit().putBoolean("playlist-fade",enabled).apply()
    }
    fun disconnect() {
        playlistJob?.cancel(); stopPlaybackService(); action?.cancel(); ble.disconnect(); notes.clear()
        mutableUi.value=mutableUi.value.copy(playing=null,playlistActive=false)
    }
    fun select(uri: String) { mutableUi.value=mutableUi.value.copy(selected=uri) }
    private fun saveLibrary() {
        val array=JSONArray()
        mutableUi.value.library.forEach { array.put(JSONObject().put("uri",it.uri).put("name",it.name).put("kind",it.kind)) }
        prefs.edit().putString("library",array.toString()).apply()
    }
    fun addFiles(uris: List<Uri>) {
        launchAction("ライブラリへ追加中") {
            val entries=withContext(Dispatchers.IO) {
                uris.map { uri ->
                    val resolver=getApplication<Application>().contentResolver
                    resolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    val name=resolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use {
                        if(it.moveToFirst()) it.getString(0) else null
                    } ?: uri.lastPathSegment.orEmpty()
                    val extension=name.substringAfterLast('.').lowercase()
                    require(extension in listOf("spc","mid","midi","wav")) { "$name は対応していません" }
                    LibrarySong(uri.toString(),name,if(extension=="mid" || extension=="midi") "MIDI" else extension.uppercase())
                }
            }
            val songs=(mutableUi.value.library+entries).distinctBy { it.uri }.take(64)
            mutableUi.value=mutableUi.value.copy(library=songs,selected=entries.firstOrNull()?.uri ?: mutableUi.value.selected)
            saveLibrary()
        }
    }
    fun removeSelected() {
        if(mutableUi.value.busy) return
        if(mutableUi.value.playlistActive) return
        val remaining=mutableUi.value.library.filterNot { it.uri==mutableUi.value.selected }
        mutableUi.value=mutableUi.value.copy(library=remaining,selected=remaining.firstOrNull()?.uri,playlist=mutableUi.value.playlist.filter { uri -> remaining.any { it.uri==uri } }); savePlaylist()
        saveLibrary()
    }
    fun transferSelected() {
        val entry=mutableUi.value.library.firstOrNull { it.uri==mutableUi.value.selected } ?: return
        if(mutableUi.value.playlistActive) return
        if(entry.kind=="WAV") { streamEntry(entry); return }
        launchAction("曲データを準備中",true) { transferEntry(entry) }
    }
    fun wavFormat(rate: Int,channels: Int) {
        if(mutableUi.value.busy) return
        require(rate in listOf(16000,32000) && channels in 1..2)
        mutableUi.value=mutableUi.value.copy(wavRate=rate,wavChannels=channels)
        prefs.edit().putInt("wav-rate",rate).putInt("wav-channels",channels).apply()
    }
    private fun streamEntry(entry: LibrarySong) {
        launchAction("WAVストリーミングを準備中",true) {
            startPlaybackService()
            try {
                withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openInputStream(Uri.parse(entry.uri))?.use { input ->
                        val source=WavBrrSource(input,mutableUi.value.wavRate,mutableUi.value.wavChannels)
                        mutableUi.value=mutableUi.value.copy(streaming=true,playing=PreparedSong(entry.name.substringBeforeLast('.'),
                            "${source.outputRate/1000} kHz ${if(source.outputChannels==2) "STEREO" else "MONO"} · ストリーミング","WAV",byteArrayOf(),source.durationMs))
                        ble.streamWav(source) { elapsed,total ->
                            mutableUi.value=mutableUi.value.copy(stage="WAV STREAM · ${elapsed/1000} / ${total/1000} 秒",
                                progress=elapsed.toFloat()/total,cancellable=true)
                        }
                    } ?: error("WAVファイルを開けません")
                }
            } finally { mutableUi.value=mutableUi.value.copy(streaming=false); stopPlaybackService() }
        }
    }
    private suspend fun transferEntry(entry: LibrarySong): PreparedSong {
            val song=withContext(Dispatchers.Default) {
                val data=withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openInputStream(Uri.parse(entry.uri))?.use {
                        val out=ByteArrayOutputStream(); val buffer=ByteArray(8192)
                        while(out.size()<=16*1024*1024) {
                            val read=it.read(buffer); if(read<0) break
                            out.write(buffer,0,read)
                        }
                        val bytes=out.toByteArray()
                        require(bytes.size<=16*1024*1024) { "SPC・MIDIファイルは16 MB以下にしてください" }
                        bytes
                    } ?: error("ファイルを開けません。ライブラリへ追加し直してください")
                }
                SongCodec.prepare(entry.name,data)
            }
            val address=ble.link.value.address
            try { retryTransfer(recover={ attempt,error ->
                android.util.Log.w("Playlist","retry=$attempt title=${song.title}",error)
                mutableUi.value=mutableUi.value.copy(stage="再転送 $attempt / 3 · ${song.title}",progress=null,cancellable=true)
                delay((attempt-1)*1000L)
                // Reconnect after a timeout too: a delayed GATT callback must not acknowledge a new write.
                if(address!=null && (!ble.link.value.ready || error is TimeoutCancellationException ||
                    (error is IllegalStateException && error !is DeviceCommandException))) ble.connect(address)
                else ble.command(19)
            }) {
            if(!ble.link.value.ready && address!=null) ble.connect(address)
            mutableUi.value=mutableUi.value.copy(stage="ESP32へ転送中",progress=0f,cancellable=true)
            ble.upload(song.bytes) { done,total -> mutableUi.value=mutableUi.value.copy(progress=done.toFloat()/total) }
            mutableUi.value=mutableUi.value.copy(stage=if(song.kind=="MIDI") "MIDI音源を準備中" else "SHVC-SOUNDへ転送中",progress=null,cancellable=false)
            ble.command(2)
            mutableUi.value=mutableUi.value.copy(playing=song)
            } } catch(e: Exception) {
                currentCoroutineContext().ensureActive()
                if(e is CancellationException && e !is TimeoutCancellationException) throw e
                rememberFailure(entry); throw e
            }
            clearTransferFailure()
        return song
    }
    private fun startPlaybackService() {
        getApplication<Application>().startForegroundService(Intent(getApplication(),PlaybackService::class.java))
    }
    private fun stopPlaybackService() {
        getApplication<Application>().stopService(Intent(getApplication(),PlaybackService::class.java))
    }
    private fun savePlaylist() {
        prefs.edit().putString("playlist",JSONArray(mutableUi.value.playlist).toString())
            .putInt("playlist-seconds",mutableUi.value.fallbackSeconds)
            .putBoolean("playlist-tags",mutableUi.value.useTimeTags)
            .putBoolean("playlist-repeat",mutableUi.value.playlistRepeat).apply()
    }
    fun enqueueSelected() {
        val item=mutableUi.value.library.firstOrNull { it.uri==mutableUi.value.selected } ?: return
        if(item.kind!="SPC") { report("再生リストにはSPCを追加してください"); return }
        if(mutableUi.value.playlistActive) return
        mutableUi.value=mutableUi.value.copy(playlist=mutableUi.value.playlist+item.uri); savePlaylist()
    }
    fun moveQueue(index: Int,direction: Int) {
        if(mutableUi.value.playlistActive) return
        val queue=mutableUi.value.playlist.toMutableList(); val target=index+direction
        if(index !in queue.indices || target !in queue.indices) return
        val item=queue.removeAt(index); queue.add(target,item)
        mutableUi.value=mutableUi.value.copy(playlist=queue); savePlaylist()
    }
    fun removeQueue(index: Int) {
        if(mutableUi.value.playlistActive) return
        mutableUi.value=mutableUi.value.copy(playlist=mutableUi.value.playlist.filterIndexed { i,_ -> i!=index }); savePlaylist()
    }
    fun playlistSettings(seconds: Int,tags: Boolean,repeat: Boolean) {
        mutableUi.value=mutableUi.value.copy(fallbackSeconds=seconds.coerceIn(1,3600),useTimeTags=tags,playlistRepeat=repeat); savePlaylist()
    }
    fun startPlaylist() = startPlaylist(0,null)
    private fun startPlaylist(startIndex: Int,savedQueue: List<LibrarySong>?) {
        if(mutableUi.value.busy || mutableUi.value.playlistActive || (savedQueue==null && mutableUi.value.playlist.isEmpty())) return
        val queue=savedQueue ?: mutableUi.value.playlist.map { uri -> mutableUi.value.library.first { it.uri==uri } }
        val useTags=mutableUi.value.useTimeTags
        val fallback=mutableUi.value.fallbackSeconds*1000L
        val repeat=mutableUi.value.playlistRepeat
        val useFade=mutableUi.value.fadeEnabled
        startPlaybackService()
        playlistJob=viewModelScope.launch {
            mutableUi.value=mutableUi.value.copy(playlistActive=true,busy=true,stage="音源の状態を確認中",error=null)
            var firstIndex=startIndex
            try {
                readAmpState()
                do {
                    for(index in firstIndex until queue.size) {
                        val item=queue[index]
                        ensureActive()
                        mutableUi.value=mutableUi.value.copy(playlistIndex=index,selected=item.uri,busy=true,
                            stage="曲データを準備中",progress=null,cancellable=true)
                        val song=try { transferEntry(item) }
                        catch(e: Exception) {
                            currentCoroutineContext().ensureActive()
                            if(e is CancellationException && e !is TimeoutCancellationException) throw e
                            rememberFailure(item,queue,index); throw e
                        }
                        mutableUi.value=mutableUi.value.copy(busy=false,stage="",progress=null,cancellable=false)
                        val duration=if(useTags) song.durationMs else null
                        android.util.Log.i("Playlist","track=$index title=${song.title} durationMs=${duration ?: fallback}")
                        val deadline=android.os.SystemClock.elapsedRealtime()+(duration ?: fallback)
                        val length=duration ?: fallback
                        val fade=if(useTags && song.fadeMs>0) song.fadeMs else 2000L
                        val fadeLength=fade.coerceAtMost(minOf(length,60000L))
                        var fading=false
                        while(android.os.SystemClock.elapsedRealtime()<deadline) {
                            if(!fading && useFade && mutableUi.value.ampProfile==1 &&
                                android.os.SystemClock.elapsedRealtime()>=deadline-fadeLength) {
                                ble.command(14,SongCodec.u32((deadline-android.os.SystemClock.elapsedRealtime()).coerceIn(1,60000)))
                                fading=true
                                android.util.Log.i("Playlist","fade title=${song.title} durationMs=$fadeLength")
                            }
                            ensureActive(); check(ble.link.value.ready) { "音源との接続が切れました" }
                            mutableUi.value=mutableUi.value.copy(remainingSeconds=((deadline-android.os.SystemClock.elapsedRealtime()+999)/1000).toInt())
                            delay(250)
                        }
                    }
                firstIndex=0
                } while(repeat)
                ble.command(3)
            } catch(e: Exception) {
                currentCoroutineContext().ensureActive()
                if(e is CancellationException && e !is TimeoutCancellationException) throw e
                android.util.Log.e("Playlist","playback failed",e)
                report(e.message ?: "連続再生に失敗しました")
            }
            finally {
                mutableUi.value=mutableUi.value.copy(playlistActive=false,busy=false,stage="",progress=null,cancellable=false,remainingSeconds=0)
                stopPlaybackService()
            }
        }
    }
    fun stopPlaylist() {
        val job=playlistJob; job?.cancel()
        viewModelScope.launch { job?.join(); runCatching { ble.command(3) }.onFailure { report(it.message ?: "停止できません") } }
    }
    fun cancelTransfer() { if(mutableUi.value.cancellable) { if(mutableUi.value.playlistActive) stopPlaylist() else action?.cancel() } }
    fun play() = launchAction("音源を準備中") { ble.command(2) }
    fun stop() { if(mutableUi.value.streaming) action?.cancel() else if(mutableUi.value.playlistActive) stopPlaylist() else launchAction("停止中") { ble.command(3); notes.clear() } }
    fun mute(value: Boolean) = launchAction("ミュートを変更中") { ble.command(4,byteArrayOf(if(value) 1 else 0)) }
    fun loop(value: Boolean) = launchAction("ループを変更中") { ble.command(8,byteArrayOf(if(value) 1 else 0)) }
    fun boot(value: Boolean) = launchAction("起動設定を変更中") { ble.command(9,byteArrayOf(if(value) 1 else 0)) }
    fun refresh() = launchAction("状態を確認中") { ble.command(1); readAmpState() }
    fun gain(value: Float) = launchAction(if(value==0f) "消音中" else "SPC音量を反映中 · 曲頭から再開") {
        require(value in 0f..4f); ble.command(11,SongCodec.u16(Math.rint(value*256.0).toInt()))
    }
    fun midiMode() = launchAction("MIDI音源を準備中") { ble.command(6); mutableUi.value=mutableUi.value.copy(playing=null) }
    fun parameters(master: Int,channel: Int,volume: Int,pan: Int,program: Int,expression: Int) = launchAction("MIDI設定を反映中") {
        require(channel in 0..15 && listOf(master,volume,pan,program,expression).all { it in 0..127 })
        ble.command(5,byteArrayOf(master.toByte()))
        for((cc,value) in listOf(7 to volume,10 to pan,11 to expression)) ble.command(7,byteArrayOf(channel.toByte(),cc.toByte(),value.toByte()))
        ble.command(10,byteArrayOf(channel.toByte(),program.toByte()))
    }
    fun note(note: Int,down: Boolean,channel: Int=0) {
        if(down && (mutableUi.value.busy || ble.status.value?.mode!=2)) return
        if(down) notes.add(channel to note) else notes.remove(channel to note)
        viewModelScope.launch {
            runCatching { ble.midi(byteArrayOf(((if(down) 0x90 else 0x80) or channel).toByte(),note.toByte(),(if(down) 100 else 0).toByte())) }
                .onFailure { report(it.message ?: "MIDI送信に失敗") }
        }
    }
    fun releaseNotes() {
        notes.toList().forEach { (channel,note) -> note(note,false,channel) }
    }
    override fun onCleared() { playlistJob?.cancel(); stopPlaybackService(); ble.disconnect(); super.onCleared() }
}
