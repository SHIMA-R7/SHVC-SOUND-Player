package com.shvc.sounddeck

import android.annotation.SuppressLint
import android.bluetooth.*
import android.bluetooth.le.*
import android.content.Context
import android.os.Build
import android.os.ParcelUuid
import android.os.SystemClock
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

class DeviceCommandException(val code: Int,message: String): IllegalStateException(message)

data class FoundDeck(val address: String,val name: String,val rssi: Int)
data class LinkState(val label: String="未接続",val ready: Boolean=false,val scanning: Boolean=false,
    val devices: List<FoundDeck> = emptyList(),val address: String?=null)

@SuppressLint("MissingPermission")
class BleDeck(private val context: Context,private val scope: CoroutineScope,private val uploadWindow: Int=16,private val reliableUpload: Boolean=false) {
    companion object {
        val SERVICE: UUID=UUID.fromString("89e30000-3c3b-4df7-a74a-25fdd879b40c")
        val COMMAND: UUID=UUID.fromString("89e30001-3c3b-4df7-a74a-25fdd879b40c")
        val STATUS: UUID=UUID.fromString("89e30002-3c3b-4df7-a74a-25fdd879b40c")
        val MIDI_SERVICE: UUID=UUID.fromString("03b80e5a-ede8-4b33-a751-6ce34ec4c700")
        val MIDI: UUID=UUID.fromString("7772e5db-3868-4112-a1a9-f2669d106bf3")
        val CCCD: UUID=UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }
    private val adapter=(context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
    private val mutableLink=MutableStateFlow(LinkState())
    val link=mutableLink.asStateFlow()
    private val mutableStatus=MutableStateFlow<DeviceStatus?>(null)
    val status=mutableStatus.asStateFlow()
    private var scanJob: Job?=null
    @Volatile private var gatt: BluetoothGatt?=null
    private var commandChar: BluetoothGattCharacteristic?=null
    private var midiChar: BluetoothGattCharacteristic?=null
    @Volatile private var mtu=23
    private var sequence=0
    private val operation=Mutex()
    private val stateLock=Any()
    private var ready: CompletableDeferred<Unit>?=null
    private var written: CompletableDeferred<Unit>?=null
    private var ack: CompletableDeferred<DeviceStatus>?=null
    private var expectedSeq=0
    private var expectedOp=0
    private var generation=0

    private val scanCallback=object: ScanCallback() {
        override fun onScanResult(callbackType: Int,result: ScanResult) {
            val name=result.scanRecord?.deviceName ?: "SHVC-SOUND Player"
            val deck=FoundDeck(result.device.address,name,result.rssi)
            synchronized(stateLock) {
                val found=(mutableLink.value.devices.filterNot { it.address==deck.address }+deck).sortedByDescending { it.rssi }
                mutableLink.value=mutableLink.value.copy(devices=found)
            }
        }
        override fun onScanFailed(errorCode: Int) { stopScan(); mutableLink.value=mutableLink.value.copy(label="検索に失敗 ($errorCode)") }
    }
    fun scan() {
        require(adapter!=null && adapter.isEnabled) { "AndroidのBluetoothをONにしてください" }
        stopScan()
        mutableLink.value=mutableLink.value.copy(scanning=true,devices=emptyList(),label="近くの音源を検索中")
        adapter.bluetoothLeScanner.startScan(listOf(ScanFilter.Builder().setServiceUuid(ParcelUuid(SERVICE)).build()),
            ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(),scanCallback)
        scanJob=scope.launch { delay(12000); stopScan() }
    }
    fun stopScan() {
        scanJob?.cancel(); scanJob=null
        if(mutableLink.value.scanning) runCatching { adapter?.bluetoothLeScanner?.stopScan(scanCallback) }
        mutableLink.value=mutableLink.value.copy(scanning=false,label=if(mutableLink.value.ready) "接続済み" else "未接続")
    }
    private fun fail(error: Throwable) {
        synchronized(stateLock) {
            ready?.completeExceptionally(error); written?.completeExceptionally(error); ack?.completeExceptionally(error)
        }
    }
    fun disconnect() {
        stopScan(); generation++
        fail(IllegalStateException("Bluetooth接続が切れました"))
        val old=gatt; gatt=null; commandChar=null; midiChar=null; mtu=23
        runCatching { old?.disconnect() }; runCatching { old?.close() }
        mutableStatus.value=null; mutableLink.value=LinkState()
    }
    suspend fun connect(address: String) {
        disconnect()
        require(adapter!=null && adapter.isEnabled) { "AndroidのBluetoothをONにしてください" }
        val token=generation
        val completion=CompletableDeferred<Unit>(); synchronized(stateLock) { ready=completion }
        mutableLink.value=LinkState(label="音源に接続中",address=address)
        val callback=object: BluetoothGattCallback() {
            private fun valid(g: BluetoothGatt): Boolean = token==generation && (gatt==null || gatt===g)
            override fun onConnectionStateChange(g: BluetoothGatt,status: Int,newState: Int) {
                if(!valid(g)) return
                if(status!=BluetoothGatt.GATT_SUCCESS || newState==BluetoothProfile.STATE_DISCONNECTED) {
                    fail(IllegalStateException("音源との接続が切れました ($status)"))
                    g.close(); if(gatt===g) gatt=null
                    mutableLink.value=mutableLink.value.copy(ready=false,label="切断"); mutableStatus.value=null
                } else if(newState==BluetoothProfile.STATE_CONNECTED) {
                    if(!g.requestMtu(517)) g.discoverServices()
                }
            }
            override fun onMtuChanged(g: BluetoothGatt,value: Int,status: Int) {
                if(!valid(g)) return
                if(status==BluetoothGatt.GATT_SUCCESS) mtu=value
                if(!g.discoverServices()) fail(IllegalStateException("音源のサービスを取得できません"))
            }
            override fun onServicesDiscovered(g: BluetoothGatt,status: Int) {
                if(!valid(g)) return
                if(status!=BluetoothGatt.GATT_SUCCESS) { fail(IllegalStateException("サービス取得に失敗 ($status)")); return }
                val control=g.getService(SERVICE)
                commandChar=control?.getCharacteristic(COMMAND)
                val notify=control?.getCharacteristic(STATUS)
                midiChar=g.getService(MIDI_SERVICE)?.getCharacteristic(MIDI)
                val descriptor=notify?.getDescriptor(CCCD)
                if(commandChar==null || notify==null || descriptor==null || !g.setCharacteristicNotification(notify,true)) {
                    fail(IllegalStateException("対応するSHVC-SOUNDファームが見つかりません")); return
                }
                val started=if(Build.VERSION.SDK_INT>=33) g.writeDescriptor(descriptor,BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)==BluetoothStatusCodes.SUCCESS
                else { @Suppress("DEPRECATION") descriptor.value=BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE; @Suppress("DEPRECATION") g.writeDescriptor(descriptor) }
                if(!started) fail(IllegalStateException("通知を有効にできません"))
            }
            override fun onDescriptorWrite(g: BluetoothGatt,d: BluetoothGattDescriptor,status: Int) {
                android.util.Log.d("SoundDeck","CCCD status=$status")
                if(!valid(g) || d.uuid!=CCCD) return
                if(status==BluetoothGatt.GATT_SUCCESS) completion.complete(Unit)
                else fail(IllegalStateException("通知の設定に失敗 ($status)"))
            }
            override fun onCharacteristicWrite(g: BluetoothGatt,c: BluetoothGattCharacteristic,status: Int) {
                android.util.Log.d("SoundDeck","write uuid=${c.uuid} status=$status")
                if(!valid(g)) return
                synchronized(stateLock) {
                    if(status==BluetoothGatt.GATT_SUCCESS) written?.complete(Unit)
                    else written?.completeExceptionally(IllegalStateException("Bluetooth送信に失敗 ($status)"))
                }
            }
            @Deprecated("Legacy callback")
            override fun onCharacteristicChanged(g: BluetoothGatt,c: BluetoothGattCharacteristic) {
                @Suppress("DEPRECATION") if(valid(g)) received(c.uuid,c.value)
            }
            override fun onCharacteristicChanged(g: BluetoothGatt,c: BluetoothGattCharacteristic,value: ByteArray) {
                if(valid(g)) received(c.uuid,value)
            }
        }
        try {
            gatt=adapter.getRemoteDevice(address).connectGatt(context,false,callback,BluetoothDevice.TRANSPORT_LE)
            withTimeout(25000) { completion.await() }
            command(1)
            mutableLink.value=mutableLink.value.copy(ready=true,label="接続済み")
        } catch(e: Throwable) { disconnect(); throw e }
        finally { synchronized(stateLock) { ready=null } }
    }
    private fun received(uuid: UUID,bytes: ByteArray) {
        android.util.Log.d("SoundDeck","notify uuid=$uuid bytes=${bytes.joinToString("") { "%02x".format(it.toInt() and 255) }}")
        if(uuid!=STATUS) return
        val result=runCatching { DeviceStatus.parse(bytes) }.getOrElse { fail(it); return }
        mutableStatus.value=result
        synchronized(stateLock) { if(result.sequence==expectedSeq && result.op==expectedOp) ack?.complete(result) }
    }
    private suspend fun write(c: BluetoothGattCharacteristic,bytes: ByteArray,type: Int) {
        val active=gatt ?: error("音源に接続してください")
        val done=CompletableDeferred<Unit>(); synchronized(stateLock) { written=done }
        try {
            val started=if(Build.VERSION.SDK_INT>=33) active.writeCharacteristic(c,bytes,type)==BluetoothStatusCodes.SUCCESS
            else { @Suppress("DEPRECATION") c.value=bytes; c.writeType=type; @Suppress("DEPRECATION") active.writeCharacteristic(c) }
            check(started) { "Bluetooth送信を開始できません" }
            withTimeout(10000) { done.await() }
        } finally { synchronized(stateLock) { written=null } }
    }
    suspend fun command(op: Int,payload: ByteArray=byteArrayOf(),allowValidationError: Boolean=false): DeviceStatus = operation.withLock {
        val c=commandChar ?: error("音源に接続してください")
        sequence=sequence%65535+1
        val done=CompletableDeferred<DeviceStatus>()
        synchronized(stateLock) { expectedSeq=sequence; expectedOp=op; ack=done }
        try {
            android.util.Log.d("SoundDeck","command seq=$sequence op=$op")
            write(c,SongCodec.u16(sequence)+byteArrayOf(op.toByte())+payload,BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
            val result=withTimeout(120000) { done.await() }
            if(!(result.code==0 || (allowValidationError && result.code==2))) throw DeviceCommandException(result.code,when(result.code) { 1->"この再生モードでは操作できません"; 2->"曲データの検証に失敗しました"; 3->"ESPへの保存に失敗しました"; 4->"SHVC-SOUNDとの通信に失敗しました"; else->"音源からエラー (${result.code})" })
            result
        } finally { synchronized(stateLock) { ack=null } }
    }
    suspend fun upload(bytes: ByteArray,progress: (Int,Int)->Unit) {
        require(bytes.size in 16..SongCodec.MAX_SONG)
        val active=gatt ?: error("音源に接続してください")
        try {
            // A rejected priority request remains compatible with older phones.
            if(active.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)) delay(500)
            command(16,SongCodec.begin(bytes))
            val checked=((mutableStatus.value?.flags ?: 0) and 128)!=0
            val size=(mtu-(if(checked) 14 else 10)).coerceIn(9,if(checked) 501 else 505)
            val c=commandChar ?: error("音源に接続してください")
            val windowed=((mutableStatus.value?.flags ?: 0) and 32)!=0 &&
                c.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE != 0
            var offset=0
            var repairs=0
            while(offset<bytes.size) {
                currentCoroutineContext().ensureActive()
                if(windowed) {
                    val windowStart=offset
                    operation.withLock {
                        repeat(uploadWindow.coerceIn(1,32)) {
                            if(offset<bytes.size) {
                                val end=minOf(offset+size,bytes.size)
                                sequence=sequence%65535+1
                                val data=bytes.copyOfRange(offset,end)
                                val crc=if(checked) SongCodec.u32(java.util.zip.CRC32().apply { update(data) }.value) else byteArrayOf()
                                write(c,SongCodec.u16(sequence)+byteArrayOf(if(checked) 21 else 20)+SongCodec.u32(offset.toLong())+crc+
                                    data,if(reliableUpload) BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT else BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE)
                                offset=end
                                if(!reliableUpload) delay(2) // Bound controller queues during fragmented writes.
                            }
                        }
                    }
                    // FIFO barrier confirms ESP processing, not just Android queuing.
                    val result=command(1,allowValidationError=checked)
                    if(checked && (result.code==2 || result.received!=offset.toLong())) {
                        check(result.received in windowStart.toLong()..offset.toLong() && repairs++<8) { "再送しても受信位置が一致しません" }
                        offset=result.received.toInt()
                        command(22,SongCodec.u32(offset.toLong()))
                        android.util.Log.i("SoundDeck","upload repair offset=$offset")
                    } else check(result.received==offset.toLong()) { "受信位置が一致しません" }
                } else {
                    val end=minOf(offset+size,bytes.size)
                    val result=command(17,SongCodec.u32(offset.toLong())+bytes.copyOfRange(offset,end))
                    check(result.received==end.toLong()) { "受信位置が一致しません" }
                    offset=end
                }
                progress(offset,bytes.size)
            }
            command(18)
        } catch(e: Throwable) {
            withContext(NonCancellable) { runCatching { withTimeout(3000) { command(19) } } }
            throw e
        } finally {
            if(gatt===active) runCatching { active.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_BALANCED) }
        }
    }
    internal suspend fun sendUnacknowledged(op: Int,payload: ByteArray) = operation.withLock {
        val c=commandChar ?: error("音源に接続してください")
        sequence=sequence%65535+1
        write(c,SongCodec.u16(sequence)+byteArrayOf(op.toByte())+payload,BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE)
    }
    suspend fun streamWav(source: WavBrrSource,progress: (Long,Long)->Unit): Unit = coroutineScope {
        val active=gatt ?: error("音源に接続してください")
        check(command(1).flags and 64!=0) { "ESPのストリーミング対応ファームが必要です" }
        var encoder: Job?=null
        try {
            if(active.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)) delay(500)
            command(32,SongCodec.u16(source.outputRate)+SongCodec.u32(source.totalBytes.toLong())+(if(source.outputChannels==2) byteArrayOf(2) else byteArrayOf()))
            val block=9*source.outputChannels
            val chunk=((mtu-14).coerceAtMost(if(source.outputChannels==2) 484 else 501)/block)*block
            require(chunk>=9)
            val encoded=kotlinx.coroutines.channels.Channel<ByteArray>(128)
            encoder=launch(Dispatchers.Default) {
                try {
                    while(true) {
                        val data=source.nextChunk(chunk)
                        if(data.isEmpty()) break
                        encoded.send(data)
                    }
                    encoded.close()
                } catch(e: Throwable) { encoded.close(e); throw e }
            }
            var sent=0
            var playbackStarted=false
            suspend fun send() {
                val packets=mutableListOf<Pair<Int,ByteArray>>()
                val encodeStart=SystemClock.elapsedRealtime()
                var end=sent
                repeat(if(source.outputChannels==2) { if(playbackStarted) 64 else 16 } else 4) {
                    if(end<source.totalBytes) {
                        val data=encoded.receive()
                        check(data.isNotEmpty()) { "WAV変換が途中で終了しました" }
                        packets.add(end to data); end+=data.size
                    }
                }
                val encodeMs=SystemClock.elapsedRealtime()-encodeStart
                val sendStart=SystemClock.elapsedRealtime()
                var confirmed=sent
                var repairs=0
                while(confirmed<end) {
                    for((offset,data) in packets) if(offset>=confirmed) {
                        val crc=java.util.zip.CRC32().apply { update(data) }.value
                        sendUnacknowledged(36,SongCodec.u32(offset.toLong())+SongCodec.u32(crc)+data)
                        if(source.outputChannels==1) delay(2)
                    }
                    val result=command(1,allowValidationError=true)
                    check(result.received in confirmed.toLong()..end.toLong()) { "WAV受信位置が一致しません" }
                    check(result.mode!=5) { "WAVの供給が途切れました" }
                    confirmed=result.received.toInt()
                    if(result.code==2 || confirmed!=end) {
                        check(repairs++<3) { "WAVの再送に失敗しました" }
                        check(confirmed==end || packets.any { it.first==confirmed }) { "WAV受信位置がブロック境界ではありません" }
                        command(37,SongCodec.u32(confirmed.toLong()))
                    }
                }
                android.util.Log.i("WavRate","bytes=${end-sent} encodeMs=$encodeMs sendMs=${SystemClock.elapsedRealtime()-sendStart}")
                sent=end
            }
            val lead=if(source.outputChannels==2) 45000 else minOf(56000,source.outputRate*9/4)
            while(sent<minOf(lead,source.totalBytes)) { currentCoroutineContext().ensureActive(); send() }
            command(34)
            playbackStarted=true
            val started=SystemClock.elapsedRealtime()
            while(sent<source.totalBytes || SystemClock.elapsedRealtime()-started<source.durationMs) {
                currentCoroutineContext().ensureActive()
                val elapsed=SystemClock.elapsedRealtime()-started
                val played=elapsed*source.outputRate*9*source.outputChannels/16000
                if(sent<source.totalBytes && sent-played<lead) send() else delay(20)
                progress(elapsed.coerceAtMost(source.durationMs),source.durationMs)
                if(mutableStatus.value?.mode==5) error("WAVの供給が途切れました")
            }
            progress(source.durationMs,source.durationMs)
        } finally {
            encoder?.cancel()
            withContext(NonCancellable) { runCatching { withTimeout(3000) { command(3) } } }
            if(gatt===active) runCatching { active.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_BALANCED) }
        }
    }
    suspend fun midi(bytes: ByteArray) = operation.withLock {
        val c=midiChar ?: error("MIDIサービスが見つかりません")
        val t=(SystemClock.elapsedRealtime() and 0x1FFF).toInt()
        write(c,byteArrayOf((0x80 or (t shr 7)).toByte(),(0x80 or (t and 127)).toByte())+bytes,
            BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE)
    }
}
