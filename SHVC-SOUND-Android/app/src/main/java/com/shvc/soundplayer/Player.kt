package com.shvc.soundplayer

/**
 * 再生・停止の一連の流れ。Python版 spc_play.py の play() / stop() と同じ手順。
 * 呼び出し側(MainActivity)はバックグラウンドスレッドから呼ぶこと
 * (転送に数秒かかり、UIスレッドをブロックしてはいけない)。
 */
object Player {

    fun play(
        controller: SpcController,
        spc: SpcFile,
        volumeFactor: Double = 1.0,
        ampVolume: Int? = null,
        log: (String) -> Unit = {},
    ) {
        controller.reset()

        val stub = StubBuilder.build(spc, volumeFactor)

        val head = spc.ram.copyOfRange(0x0002, 0x00F0)
        val bulk = spc.ram.copyOfRange(0x0100, 0xFFC0)
        controller.totalBytes = head.size + bulk.size + stub.size
        controller.doneBytes = 0

        // 1. メインRAMダンプを転送 ($F0-$FFは飛ばす。I/Oレジスタ領域で単純書き込み不可)
        // 重要: $0000/$0001 はIPL ROMが転送中に内部の転送先ポインタとして使うため、
        // 通常のデータ転送で書き込んではいけない。ここは$0002からにする。
        log("RAM \$0002-\$00EF 転送中...")
        controller.writeBlock(0x0002, head)
        controller.doneBytes += head.size

        log("RAM \$0100-\$FFBF 転送中...")
        controller.writeBlock(0x0100, bulk)
        controller.doneBytes += bulk.size
        // $FFC0-$FFFF (IPL ROMシャドウ領域) は転送不要

        // 2. DSPレジスタ・コントロール・タイマー・CPUレジスタをまとめて復元する
        //    実行コードを、曲データを壊さない高位アドレスに配置して実行する。
        log("復元スタブを構築・転送中...")
        if (volumeFactor != 1.0) {
            log("マスター音量・各ボイス音量を${"%.2f".format(volumeFactor)}倍に変更")
        }
        val stubAddr = 0xFFC0 - stub.size
        log("  (スタブサイズ=${stub.size}バイト, 配置アドレス=\$${"%04X".format(stubAddr)})")
        controller.writeBlock(stubAddr, stub)
        controller.doneBytes += stub.size

        log("実行開始...")
        controller.jumpTo(stubAddr)

        Thread.sleep(100)
        val p0 = controller.readPort(0)
        log("  (診断: 実行開始マーカー確認 port0=0x${"%02X".format(p0)}, 期待値=0x99)")

        if (ampVolume != null) {
            val actual = controller.setVolume(ampVolume)
            log("アンプ音量(PWMデューティ比)を $actual/255 に設定")
        }

        log("再生開始しました。")
    }

    fun stop(controller: SpcController, log: (String) -> Unit = {}) {
        controller.reset()
        log("再生を停止しました(SPC700をリセット)。")
    }
}
