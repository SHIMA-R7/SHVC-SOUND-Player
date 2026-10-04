package com.shvc.sounddeck

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.CRC32
import kotlin.math.abs
import kotlin.math.ceil

data class PreparedSong(val title: String, val detail: String, val kind: String, val bytes: ByteArray,val durationMs: Long?=null,val fadeMs: Long=0)
data class DeviceStatus(val sequence: Int, val op: Int, val code: Int, val received: Long, val total: Long,
    val mode: Int, val flags: Int, val volume: Int, val dropped: Long) {
    val muted get() = flags and 1 != 0
    val loop get() = flags and 2 != 0
    val boot get() = flags and 4 != 0
    val gainSupported get() = flags and 8 != 0
    val loadProgress get() = if(mode==4 && flags and 16 != 0 && total>0)
        (received.toFloat()/total).coerceIn(0f,1f) else null
    val ampProfile get() = if(op in 12..15 && code==0) (volume shr 8) and 3 else null
    val ampLevel get() = if(ampProfile!=null) volume and 255 else null
    val gain get() = if (gainSupported && op !in 12..15 && (mode == 1 || op == 11)) volume / 256f else null
    val modeName get() = listOf("停止", "SPC", "MIDI LIVE", "MIDI FILE", "音源へ転送中", "エラー", "WAV STREAM").getOrElse(mode) { "不明" }
    companion object {
        fun parse(data: ByteArray): DeviceStatus {
            require(data.size == 20) { "状態データの長さが不正" }
            val b = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
            return DeviceStatus(b.short.toInt() and 65535,b.get().toInt() and 255,b.get().toInt() and 255,
                b.int.toLong() and 0xffffffffL,b.int.toLong() and 0xffffffffL,b.get().toInt() and 255,
                b.get().toInt() and 255,b.short.toInt() and 65535,b.int.toLong() and 0xffffffffL)
        }
    }
}

object SongCodec {
    const val MAX_SONG = 256000
    fun u16(value: Int) = ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN).putShort(value.toShort()).array()
    fun u32(value: Long) = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(value.toInt()).array()
    fun begin(data: ByteArray) = u32(data.size.toLong()) + u32(CRC32().apply { update(data) }.value)
    private fun ByteArray.u(at: Int) = this[at].toInt() and 255
    private fun ByteArray.le16(at: Int) = u(at) or (u(at + 1) shl 8)
    private fun tag(data: ByteArray,start: Int,end: Int): String =
        String(data.copyOfRange(start,end).takeWhile { it != 0.toByte() }.toByteArray(),charset("windows-31j")).trim()
    fun prepare(name: String, data: ByteArray): PreparedSong {
        val result = when(name.substringAfterLast('.').lowercase()) {
            "spc" -> spc(name,data)
            "mid", "midi" -> midi(name,data)
            "wav" -> wav(name,data)
            else -> throw IllegalArgumentException("SPC・MIDI・16-bit PCM WAVを選んでください")
        }
        require(result.bytes.size <= MAX_SONG) { "曲データがESPの保存上限を超えています" }
        return result
    }
    fun spc(name: String,data: ByteArray): PreparedSong {
        require(data.size >= 0x10180 && String(data.copyOfRange(0,27),Charsets.US_ASCII) == "SNES-SPC700 Sound File Data") { "SPC形式が不正です" }
        val ram=data.copyOfRange(0x100,0x10100)
        val dsp=data.copyOfRange(0x10100,0x10180)
        val code=ByteArrayOutputStream()
        fun bytes(vararg values: Int) { values.forEach { code.write(it) } }
        fun write(reg: Int,value: Int) { bytes(0x8F,reg,0xF2,0x8F,value,0xF3) }
        bytes(0x8F,0x99,0xF4); write(0x6C,0x20)
        for(reg in (0..127).filter { it != 0x6C && it != 0x4C } + 0x4C) write(reg,dsp.u(reg))
        write(0x6C,dsp.u(0x6C))
        for(reg in listOf(0xF1,0xFA,0xFB,0xFC)) bytes(0x8F,ram.u(reg),reg)
        val signal=if(ram.u(0xF4) != 0x5A) 0x5A else 0xA5
        bytes(0x78,signal,0xF4,0xD0,0xFB,0x8F,0x98,0xF4,0x78,ram.u(0xF4),0xF4,0xD0,0xFB)
        bytes(0x8F,ram.u(0),0,0x8F,ram.u(1),1,0xCD,data.u(0x2B),0xBD,
            0xCD,data.u(0x2A),0x4D,0xE8,data.u(0x27),0xCD,data.u(0x28),0x8D,data.u(0x29),
            0x8E,0x5F,data.u(0x25),data.u(0x26))
        val title=if(data.u(0x23)==0x1A) tag(data,0x2E,0x4E).ifBlank { name.substringBeforeLast('.') } else name.substringBeforeLast('.')
        val game=if(data.u(0x23)==0x1A) tag(data,0x4E,0x6E) else "SPC700 SNAPSHOT"
        return PreparedSong(title,game,"SPC",bundle(ram,code.toByteArray(),signal,ram.copyOfRange(0xF4,0xF8)),spcDuration(data),spcFade(data))
    }
    internal fun spcFade(data: ByteArray): Long {
        if(data.size<0xB1 || data.u(0x23)!=0x1A) return 0
        return String(data.copyOfRange(0xAC,0xB1),Charsets.US_ASCII).trim('\u0000',' ').toLongOrNull()?.coerceIn(0,99999) ?: 0
    }
    internal fun spcDuration(data: ByteArray): Long? {
        if(data.size<0xB1 || data.u(0x23)!=0x1A) return null
        val seconds=String(data.copyOfRange(0xA9,0xAC),Charsets.US_ASCII).trim('\u0000',' ').toLongOrNull()
        val fade=String(data.copyOfRange(0xAC,0xB1),Charsets.US_ASCII).trim('\u0000',' ').toLongOrNull() ?: 0L
        return seconds?.takeIf { it in 1..999 }?.let { it*1000+fade.coerceIn(0,99999) }
    }
    private fun bundle(ram: ByteArray,stub: ByteArray,signal: Int,ports: ByteArray): ByteArray {
        val header=ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN)
            .put("HSP1".toByteArray()).putShort((0xFFC0-stub.size).toShort()).putShort(stub.size.toShort())
            .put(signal.toByte()).put(ports).put(ByteArray(3)).array()
        return header+ram+stub
    }

    private data class MidiEvent(val tick: Long,val track: Int,val order: Int,val raw: ByteArray?,val tempo: Int?)
    private class Reader(val data: ByteArray,var pos: Int=0,val end: Int=data.size) {
        fun byte(): Int { require(pos < end) { "MIDIデータが途中で終わっています" }; return data[pos++].toInt() and 255 }
        fun be16() = (byte() shl 8) or byte()
        fun be32(): Long { var n=0L; repeat(4) { n=(n shl 8) or byte().toLong() }; return n }
        fun take(n: Int): ByteArray { require(n>=0 && n<=end-pos) { "MIDIチャンクが不正" }; return data.copyOfRange(pos,pos+n).also { pos+=n } }
        fun varlen(): Int { var n=0; repeat(4) { val b=byte(); n=(n shl 7) or (b and 127); if(b and 128==0) return n }; error("MIDI可変長値が不正") }
    }
    fun midi(name: String,data: ByteArray): PreparedSong {
        val r=Reader(data)
        require(String(r.take(4))=="MThd") { "MIDIヘッダーが不正" }
        val headerLength=r.be32().toInt(); require(headerLength in 6..1024) { "MIDIヘッダー長が不正" }
        val type=r.be16(); val tracks=r.be16(); val division=r.be16(); r.take(headerLength-6)
        require(type in 0..1 && tracks in 1..256 && (type != 0 || tracks==1)) { "MIDIタイプ0・1に対応しています" }
        require(division in 1..32767) { "SMPTE時間形式には対応していません" }
        val events=mutableListOf<MidiEvent>(); var lastTick=0L
        repeat(tracks) { track ->
            require(String(r.take(4))=="MTrk") { "MIDIトラックが不正" }
            val length=r.be32(); require(length<=r.end-r.pos) { "MIDIトラック長が不正" }
            val t=Reader(r.take(length.toInt())); var tick=0L; var running=0; var order=0
            while(t.pos<t.end) {
                tick+=t.varlen(); lastTick=maxOf(lastTick,tick)
                val first=t.byte(); val status=if(first<128) { require(running in 0x80..0xEF) { "MIDIランニングステータスが不正" }; t.pos--; running } else first
                if(status<0xF0) running=status
                when {
                    status==0xFF -> {
                        val meta=t.byte(); val body=t.take(t.varlen())
                        if(meta==0x51) {
                            require(body.size==3) { "テンポデータが不正" }
                            val tempo=(body.u(0) shl 16) or (body.u(1) shl 8) or body.u(2)
                            require(tempo>0) { "テンポが0です" }; events+=MidiEvent(tick,track,order++,null,tempo)
                        }
                        if(meta==0x2F) break
                    }
                    status==0xF0 || status==0xF7 -> { t.take(t.varlen()); running=0 }
                    status in 0x80..0xEF -> {
                        val kind=status and 0xF0; val d1=t.byte(); val d2=if(kind==0xC0 || kind==0xD0) 0 else t.byte()
                        require(d1<=127 && d2<=127) { "MIDIイベント値が不正" }
                        if(kind in listOf(0x80,0x90,0xB0,0xC0,0xE0)) events+=MidiEvent(tick,track,order++,byteArrayOf(status.toByte(),d1.toByte(),d2.toByte()),null)
                    }
                    else -> error("MIDIイベント形式が不正")
                }
                require(events.size<=100000) { "MIDIイベントが多すぎます" }
            }
        }
        val out=ByteArrayOutputStream(); var previous=0L; var elapsed=0.0; var tempo=500000; var count=0
        for(e in events.sortedWith(compareBy({it.tick},{it.track},{it.order}))) {
            elapsed+=(e.tick-previous).toDouble()*tempo/division; previous=e.tick
            if(e.tempo!=null) tempo=e.tempo
            if(e.raw!=null) { out.write(u32(Math.rint(elapsed/1000).toLong())); out.write(e.raw); out.write(0); count++ }
        }
        elapsed+=(lastTick-previous).toDouble()*tempo/division
        val duration=Math.rint(elapsed/1000).toLong()
        require(count in 1..30000 && duration<=86400000) { "MIDIは最大30000イベント・24時間です" }
        return PreparedSong(name.substringBeforeLast('.'),"${count} EVENTS · TEMPO MAP","MIDI",
            "HTM1".toByteArray()+u32(count.toLong())+u32(duration)+u32(0)+out.toByteArray())
    }

    fun wav(name: String,data: ByteArray): PreparedSong {
        require(data.size>=44 && String(data.copyOfRange(0,4))=="RIFF" && String(data.copyOfRange(8,12))=="WAVE") { "WAVヘッダーが不正" }
        var pos=12; var channels=0; var rate=0; var align=0; var pcm: ByteArray?=null
        while(pos+8<=data.size) {
            val id=String(data.copyOfRange(pos,pos+4)); val size=ByteBuffer.wrap(data,pos+4,4).order(ByteOrder.LITTLE_ENDIAN).int
            require(size>=0 && size<=data.size-pos-8) { "WAVチャンクが不正" }
            if(id=="fmt ") {
                require(size>=16 && data.le16(pos+8)==1 && data.le16(pos+22)==16) { "非圧縮16-bit PCM WAVに対応しています" }
                channels=data.le16(pos+10); rate=ByteBuffer.wrap(data,pos+12,4).order(ByteOrder.LITTLE_ENDIAN).int; align=data.le16(pos+20)
            }
            if(id=="data") pcm=data.copyOfRange(pos+8,pos+8+size)
            pos+=8+size+(size and 1)
        }
        require(channels in 1..2 && rate in 4000..192000 && align==channels*2 && pcm!=null) { "WAVのチャンネル・レートが不正" }
        val samples=pcm!!; val sourceCount=minOf(samples.size/align,rate*10)
        val count=(sourceCount.toLong()*8000/rate).toInt(); require(count>0) { "WAVに音声がありません" }
        val mono=DoubleArray(sourceCount) { i ->
            (0 until channels).sumOf { c -> samples.le16(i*align+c*2).toShort().toDouble() } / channels
        }
        val resampled=DoubleArray(count) { i ->
            val x=i.toDouble()*rate/8000; val a=x.toInt().coerceAtMost(sourceCount-1); val b=minOf(a+1,sourceCount-1)
            mono[a]+(mono[b]-mono[a])*(x-a)
        }
        val peak=resampled.maxOf { abs(it) }.coerceAtLeast(1.0)
        val ints=IntArray(ceil(count/16.0).toInt()*16) { if(it<count) Math.rint(resampled[it]/peak*.8*32767).toInt() else 0 }
        val brr=ByteArrayOutputStream(); var p1=0; var p2=0
        for(block in ints.indices step 16) {
            var bestError=Double.MAX_VALUE; var bestRange=0; var bestFilter=0; var bestNib=IntArray(16); var bestP1=0; var bestP2=0
            for(filter in if(p1==0 && p2==0) 0..0 else 0..3) for(range in 0..12) {
                var a=p1; var b=p2; var error=0.0; val nib=IntArray(16)
                for(i in 0..15) {
                    val pred=when(filter) { 0->0; 1->a-(a shr 4); 2->2*a-((a*3) shr 5)-b+(b shr 4); else->2*a-((a*13) shr 6)-b+((b*3) shr 4) }
                    val n=Math.rint((ints[block+i]-pred).toDouble()/(1 shl range)).toInt().coerceIn(-8,7)
                    nib[i]=n; val decoded=(pred+((n shl range) shr 1)*2).coerceIn(-32768,32767)
                    val delta=(decoded-ints[block+i]).toDouble(); error+=delta*delta; b=a; a=decoded
                }
                if(error<bestError) { bestError=error; bestRange=range; bestFilter=filter; bestNib=nib; bestP1=a; bestP2=b }
            }
            brr.write((bestRange shl 4) or (bestFilter shl 2) or if(block+16==ints.size) 1 else 0)
            for(i in 0..15 step 2) brr.write(((bestNib[i] and 15) shl 4) or (bestNib[i+1] and 15))
            p1=bestP1; p2=bestP2
        }
        val code=ByteArrayOutputStream()
        fun bytes(vararg v: Int) { v.forEach { code.write(it) } }
        fun dsp(reg: Int,value: Int) { bytes(0x8F,reg,0xF2,0x8F,value,0xF3) }
        bytes(0x20,0x8F,0x99,0xF4); dsp(0x6C,0x60); dsp(0x5C,255)
        for(r in 0..127) if(r!=0x6C && r!=0x5C) dsp(r,0)
        for((reg,value) in listOf(0x0C to 80,0x1C to 80,0x5D to 3,0 to 96,1 to 96,2 to 0,3 to 4,4 to 0,5 to 0,7 to 127,0x5C to 0)) dsp(reg,value)
        bytes(0x78,0x5A,0xF4,0xD0,0xFB,0x8F,0x98,0xF4,0x78,0,0xF4,0xD0,0xFB)
        dsp(0x6C,0x20); dsp(0x4C,1); bytes(0x2F,0xFE)
        val stub=code.toByteArray(); val audio=brr.toByteArray()
        require(0x400+audio.size<=0xFFC0-stub.size) { "WAVが音源RAMの上限を超えています" }
        val ram=ByteArray(65536); (u16(0x400)+u16(0x400)).copyInto(ram,0x300); audio.copyInto(ram,0x400)
        return PreparedSong(name.substringBeforeLast('.'),"先頭 ${"%.1f".format(count/8000.0)}秒 · 8 kHz MONO","WAV",bundle(ram,stub,0x5A,ByteArray(4)))
    }
}
