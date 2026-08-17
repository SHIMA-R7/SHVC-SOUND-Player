package com.shvc.soundplayer

import java.io.InputStream
import java.nio.charset.Charset

/**
 * .spcファイルの解析。Python版 spc_play.py の SpcFile クラスと同じロジック。
 *
 * .spcファイル形式(オフセットは既知の標準フォーマット):
 *   0x00-0x20 : ヘッダ("SNES-SPC700 Sound File Data v0.30" 等)
 *   0x23      : タグ形式 (0x1A ならID666タグあり)
 *   0x25-0x26 : PC (リトルエンディアン)
 *   0x27      : A
 *   0x28      : X
 *   0x29      : Y
 *   0x2A      : PSW
 *   0x2B      : SP
 *   0x100-0x100FF : ARAM 64KB ダンプ
 *   0x10100-0x1017F : DSPレジスタ 128バイト
 */
class SpcFile(data: ByteArray, val displayName: String) {

    val pc: Int
    val a: Int
    val x: Int
    val y: Int
    val psw: Int
    val sp: Int
    val ram: ByteArray  // 0x10000バイト (64KB)
    val dsp: ByteArray  // 0x80バイト (128バイト)
    val tags: Map<String, String>

    init {
        if (data.size < 0x10180) {
            throw IllegalArgumentException(".spcファイルとして小さすぎます(壊れているかも)")
        }

        pc = (data[0x25].toInt() and 0xFF) or ((data[0x26].toInt() and 0xFF) shl 8)
        a = data[0x27].toInt() and 0xFF
        x = data[0x28].toInt() and 0xFF
        y = data[0x29].toInt() and 0xFF
        psw = data[0x2A].toInt() and 0xFF
        sp = data[0x2B].toInt() and 0xFF

        ram = data.copyOfRange(0x100, 0x100 + 0x10000)
        dsp = data.copyOfRange(0x10100, 0x10100 + 0x80)

        tags = if (data[0x23] == 0x1A.toByte()) {
            mapOf(
                "title" to decodeTag(data, 0x2E, 0x4E),
                "game" to decodeTag(data, 0x4E, 0x6E),
                "dumper" to decodeTag(data, 0x6E, 0x7E),
                "comment" to decodeTag(data, 0x7E, 0x9E),
                "date" to decodeTag(data, 0x9E, 0xA9),
                "seconds" to decodeTag(data, 0xA9, 0xAC),
                "artist" to decodeTag(data, 0xB1, 0xD1),
            )
        } else {
            emptyMap()
        }
    }

    companion object {
        private val CP932: Charset = Charset.forName("Shift_JIS")

        /** ID666タグの文字列フィールドをデコードする。NUL以降は切り捨てる。 */
        private fun decodeTag(data: ByteArray, start: Int, end: Int): String {
            val raw = data.copyOfRange(start, end)
            val nul = raw.indexOf(0)
            val trimmed = if (nul >= 0) raw.copyOfRange(0, nul) else raw
            return try {
                String(trimmed, CP932).trim()
            } catch (e: Exception) {
                String(trimmed, Charsets.ISO_8859_1).trim()
            }
        }

        fun fromStream(input: InputStream, displayName: String): SpcFile {
            val bytes = input.readBytes()
            return SpcFile(bytes, displayName)
        }
    }
}
