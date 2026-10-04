package com.shvc.sounddeck

import java.io.InputStream
import java.io.EOFException
import java.io.ByteArrayOutputStream
import kotlin.math.roundToInt

/** Reads and converts a WAV incrementally; no full-file PCM or BRR allocation. */
class WavBrrSource(input: InputStream,val outputRate: Int=16000,val outputChannels: Int=1) {
    private val input=input.buffered(4096)
    private var channels=0
    private var rate=0
    private var frames=0L
    private var framesRead=0L
    private var sample=0L
    private var sourceIndex=0L
    private var a=DoubleArray(outputChannels)
    private var b=DoubleArray(outputChannels)
    private var p1=IntArray(outputChannels)
    private var p2=IntArray(outputChannels)
    val samples: Long
    val totalBytes: Int
    val durationMs: Long
    init {
        require(outputRate in listOf(8000,16000,32000) && outputChannels in 1..2)
        require(String(read(4),Charsets.US_ASCII)=="RIFF") { "RIFF WAVに対応しています" }
        read(4)
        require(String(read(4),Charsets.US_ASCII)=="WAVE") { "WAV形式が不正" }
        while(true) {
            val id=String(read(4),Charsets.US_ASCII)
            val length=u32(read(4))
            if(id=="fmt ") {
                require(length in 16..65536)
                val fmt=read(length.toInt())
                require(u16(fmt,0)==1 && u16(fmt,14)==16) { "非圧縮16-bit PCM WAVに対応しています" }
                channels=u16(fmt,2); rate=u32(fmt.copyOfRange(4,8)).toInt()
                require(channels in 1..2 && rate in 4000..192000 && u16(fmt,12)==channels*2)
                if(length%2!=0L) skip(1)
            } else if(id=="data") {
                require(channels>0 && length>0 && length%(channels*2)==0L) { "WAVの音声チャンクが不正" }
                frames=length/(channels*2); break
            } else skip(length+(length and 1))
        }
        samples=(frames*outputRate+rate-1)/rate
        val bytes=(samples+15)/16*9*outputChannels
        require(bytes in 9..Int.MAX_VALUE.toLong()) { "WAVの長さが上限を超えています" }
        totalBytes=bytes.toInt(); durationMs=(samples+15)/16*16000/outputRate
        a=frame(); b=if(frames>1) frame() else a
    }
    private fun u16(bytes: ByteArray,offset: Int)=(bytes[offset].toInt() and 255) or ((bytes[offset+1].toInt() and 255) shl 8)
    private fun u32(bytes: ByteArray)=bytes.indices.fold(0L) { v,i -> v or ((bytes[i].toLong() and 255) shl (8*i)) }
    private fun read(n: Int): ByteArray {
        val bytes=ByteArray(n); var done=0
        while(done<n) { val count=input.read(bytes,done,n-done); if(count<0) throw EOFException("WAVが途中で切れています"); if(count>0) done+=count }
        return bytes
    }
    private fun skip(n: Long) {
        var left=n
        while(left>0) { val count=input.skip(left); if(count>0) left-=count else { if(input.read()<0) throw EOFException(); left-- } }
    }
    private fun frame(): DoubleArray {
        if(framesRead>=frames) return b
        val bytes=read(channels*2); framesRead++
        return DoubleArray(outputChannels) { ch -> if(outputChannels==1) (0 until channels).sumOf { u16(bytes,it*2).toShort().toDouble() }/channels else u16(bytes,(if(channels==1) 0 else ch)*2).toShort().toDouble() }
    }
    private fun nextSample(): IntArray {
        if(sample>=samples) { sample++; return IntArray(outputChannels) }
        val x=sample.toDouble()*rate/outputRate; val index=x.toLong().coerceAtMost(frames-1)
        while(sourceIndex<index) { a=b; b=frame(); sourceIndex++ }
        sample++
        return IntArray(outputChannels) { ch -> ((a[ch]+(b[ch]-a[ch])*(x-index))*.8).roundToInt().coerceIn(-32768,32767) }
    }
    fun nextChunk(maxBytes: Int): ByteArray {
        require(maxBytes>=9*outputChannels)
        val out=ByteArrayOutputStream()
        repeat(maxBytes/(9*outputChannels)) {
            if(sample<samples) {
                val frames=Array(16) { nextSample() }
                repeat(outputChannels) { ch -> out.write(encode(IntArray(16) { frames[it][ch] },ch)) }
            }
        }
        return out.toByteArray()
    }
    private fun encode(values: IntArray,ch: Int): ByteArray {
        var bestError=Double.MAX_VALUE; var bestRange=0; var bestFilter=0
        var bestNib=IntArray(16); var nextP1=0; var nextP2=0
        for(filter in if(p1[ch]==0 && p2[ch]==0) 0..0 else 0..3) {
            var prev=p1[ch]; var prev2=p2[ch]; var peak=0
            for(value in values) {
                val pred=when(filter) { 0->0; 1->prev-(prev shr 4); 2->2*prev-((prev*3) shr 5)-prev2+(prev2 shr 4); else->2*prev-((prev*13) shr 6)-prev2+((prev2*3) shr 4) }
                peak=maxOf(peak,kotlin.math.abs(value-pred)); prev2=prev; prev=value
            }
            var estimate=0
            while(estimate<12 && peak>7*(1 shl estimate)) estimate++
            for(range in maxOf(0,estimate-1)..minOf(12,estimate+1)) {
            var a=p1[ch]; var b=p2[ch]; var error=0.0; val nib=IntArray(16)
            for(i in 0..15) {
                val pred=when(filter) { 0->0; 1->a-(a shr 4); 2->2*a-((a*3) shr 5)-b+(b shr 4); else->2*a-((a*13) shr 6)-b+((b*3) shr 4) }
                val n=Math.rint((values[i]-pred).toDouble()/(1 shl range)).toInt().coerceIn(-8,7)
                nib[i]=n; val decoded=(pred+((n shl range) shr 1)*2).coerceIn(-32768,32767)
                val delta=(decoded-values[i]).toDouble(); error+=delta*delta; b=a; a=decoded
            }
            if(error<bestError) { bestError=error; bestRange=range; bestFilter=filter; bestNib=nib; nextP1=a; nextP2=b }
        }
        }
        p1[ch]=nextP1; p2[ch]=nextP2
        return ByteArray(9).also { bytes ->
            bytes[0]=((bestRange shl 4) or (bestFilter shl 2)).toByte()
            for(i in 0..15 step 2) bytes[1+i/2]=(((bestNib[i] and 15) shl 4) or (bestNib[i+1] and 15)).toByte()
        }
    }
}
