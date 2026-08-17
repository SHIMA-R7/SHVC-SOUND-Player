package com.shvc.soundplayer

import java.io.ByteArrayOutputStream

/**
 * DSPレジスタ・コントロール・タイマー・CPUレジスタをすべて復元して実行を
 * 開始する、SPC700側で実際に動くコードを組み立てる。
 * Python版 spc_play.py の build_final_stub() / boost_master_volume() と
 * 完全に同じロジック(バイト列も一致するはず)。
 */
object StubBuilder {

    /**
     * マスター音量(MVOLL/MVOLR)と各ボイスのVOLL/VOLRをまとめて底上げした
     * DSPレジスタ配列を返す(元は変更しない)。
     *
     * S-DSPの音量レジスタは符号付き8bit(-128〜127)。正の値が大きいほど
     * 音量が大きい(負値は位相反転付きの音量で、曲データで意図的に使われる
     * ことがあるため符号は保持する)。単純に factor 倍して、
     * signed 8bit の範囲(-128〜127)でクランプする。
     */
    fun boostMasterVolume(dsp: ByteArray, factor: Double): ByteArray {
        val out = dsp.copyOf()
        val regs = mutableListOf(0x0C, 0x1C) // MVOLL, MVOLR
        for (v in 0..7) {
            regs.add(v * 0x10 + 0x00)
            regs.add(v * 0x10 + 0x01)
        }
        for (reg in regs) {
            val raw = dsp[reg].toInt() and 0xFF
            val signed = if (raw >= 128) raw - 256 else raw
            var boosted = Math.round(signed * factor).toInt()
            boosted = boosted.coerceIn(-128, 127)
            out[reg] = (boosted and 0xFF).toByte()
        }
        return out
    }

    /**
     * ※既知の制限: スタブは約800バイトあり、$FFC0直下ということは
     *   $FC9x-$FFBF付近を占める。この領域はメインRAM転送($0100-$FFBF)の
     *   範囲内なので、曲データを800バイト分上書きしてしまう。
     *   この領域をサンプルデータやエコーバッファに使っている曲では
     *   ノイズや音の破綻が出る(Python版と同じ制限)。
     */
    fun build(spc: SpcFile, volumeFactor: Double = 1.0): ByteArray {
        val out = ByteArrayOutputStream()

        val dsp = if (volumeFactor == 1.0) spc.dsp else boostMasterVolume(spc.dsp, volumeFactor)

        // 診断: スタブが実際に実行開始されたか確認するためのマーカー。
        // 実行されれば$F4(host側から見てport0)に0x99が現れるはず。
        out.write(0x8F); out.write(0x99); out.write(0xF4) // mov $F4,#0x99

        // DSPレジスタ128個を復元する。順序が重要:
        //  1. FLG($6C)にまず $20 を書く。soft reset(bit7)とmute(bit6)を解除しつつ、
        //     エコー書き込みは禁止(bit5=1)のままにする。
        //  2. FLG/KON以外の126個を復元(この中でESA/EDLが正しい値になる)。
        //  3. KON($4C)を書いてキーオン。
        //  4. 最後にFLG($6C)へ保存値を書き、必要ならエコーを有効化する。
        out.write(0x8F); out.write(0x6C); out.write(0xF2)
        out.write(0x8F); out.write(0x20); out.write(0xF3)

        val order = (0 until 0x80).filter { it != 0x6C && it != 0x4C } + 0x4C
        for (i in order) {
            out.write(0x8F); out.write(i); out.write(0xF2)
            out.write(0x8F); out.write(dsp[i].toInt() and 0xFF); out.write(0xF3)
        }

        out.write(0x8F); out.write(0x6C); out.write(0xF2)
        out.write(0x8F); out.write(dsp[0x6C].toInt() and 0xFF); out.write(0xF3)

        // コントロールレジスタ・タイマー分周値を復元
        out.write(0x8F); out.write(spc.ram[0xF1].toInt() and 0xFF); out.write(0xF1)
        out.write(0x8F); out.write(spc.ram[0xFA].toInt() and 0xFF); out.write(0xFA)
        out.write(0x8F); out.write(spc.ram[0xFB].toInt() and 0xFF); out.write(0xFB)
        out.write(0x8F); out.write(spc.ram[0xFC].toInt() and 0xFF); out.write(0xFC)

        // CPUレジスタ復元+ジャンプ
        // $00/$01 はメインRAM転送であえてスキップしている
        // (IPL ROMが転送中にこの2バイトを内部の転送先ポインタとして使うため)ので、
        // ここで実データを明示的に書き戻す。
        out.write(0x8F); out.write(spc.ram[0x00].toInt() and 0xFF); out.write(0x00) // mov $00,#byte0
        out.write(0x8F); out.write(spc.ram[0x01].toInt() and 0xFF); out.write(0x01) // mov $01,#byte1
        out.write(0xCD); out.write(spc.sp)        // mov x,#sp
        out.write(0xBD)                            // mov sp,x
        out.write(0xCD); out.write(spc.psw)       // mov x,#psw
        out.write(0x4D)                             // push x
        out.write(0xE8); out.write(spc.a)         // mov a,#a
        out.write(0xCD); out.write(spc.x)         // mov x,#x
        out.write(0x8D); out.write(spc.y)         // mov y,#y
        out.write(0x8E)                             // pop psw
        out.write(0x5F); out.write(spc.pc and 0xFF); out.write((spc.pc shr 8) and 0xFF) // jmp !abs pc

        return out.toByteArray()
    }
}
