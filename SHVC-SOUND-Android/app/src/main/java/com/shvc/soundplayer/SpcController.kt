package com.shvc.soundplayer

import com.hoho.android.usbserial.driver.UsbSerialPort
import com.hoho.android.usbserial.util.SerialInputOutputManager
import java.io.IOException
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * SHVC-SOUND(SPC700 IPL ROM)への転送プロトコル。
 *
 * spc_uploader.ino (Arduino側ファームウェア、実機検証済み) と1バイトも
 *違わないように定数・シーケンスを合わせている。詳細な設計判断は
 * spc_uploader.ino / spc_play.py 側のコメントを参照。
 *
 * 重要: PING_INTERVAL(64)とボーレート(500000)はファームウェア側と
 * 完全に一致させる必要がある。ここだけ変えても通信できない。
 */
class SpcController(
    private val port: UsbSerialPort,
    private val log: (String) -> Unit = {},
    private val onProgress: (done: Int, total: Int) -> Unit = { _, _ -> },
) {
    companion object {
        const val BAUD_RATE = 500000

        private const val CMD_RESET = 0x01
        private const val CMD_SETADDR = 0x02
        private const val CMD_SENDBYTES = 0x03
        private const val CMD_READPORT = 0x04
        private const val CMD_SETVOLUME = 0x05

        private const val ACK_RESET = 0x01
        private const val ACK_SETADDR = 0x02
        private const val ACK_SENDBYTES = 0x03

        private const val MARKER_BYTE_OK = 0xCD
        private const val MARKER_TIMEOUT = 0xEE

        // ファームウェア側 PING_INTERVAL と一致させること。
        private const val PING_INTERVAL = 64
    }

    var totalBytes: Int = 0
    var doneBytes: Int = 0

    class TransferCancelled : Exception()

    // 受信は port.read() による同期ポーリングではなく、ライブラリ公式推奨の
    // SerialInputOutputManager(専用スレッドで継続的にUSB受信バッファを
    // 汲み出し続ける方式)を使う。機種によっては同期read()方式だと
    // 最初の1回は動いても、以降のやり取りで詰まることがあるため。
    private val rxQueue = LinkedBlockingQueue<Byte>()

    private val ioManager = SerialInputOutputManager(port, object : SerialInputOutputManager.Listener {
        override fun onNewData(data: ByteArray) {
            for (b in data) rxQueue.offer(b)
        }
        override fun onRunError(e: Exception) {
            log("受信スレッドエラー: ${e.message}")
        }
    })

    init {
        ioManager.start()
    }

    /** USB接続を閉じる前に呼ぶこと。 */
    fun stopIo() {
        ioManager.stop()
    }

    private var cancelled: (() -> Boolean)? = null

    fun setCancelCheck(check: () -> Boolean) {
        cancelled = check
    }

    private fun checkCancel() {
        if (cancelled?.invoke() == true) throw TransferCancelled()
    }

    // ---------------------------------------------------------- 低レベルI/O

    // USBフルスピードのバルク転送は1パケット最大64バイト。ちょうど64バイト
    // (境界値)を1回のwrite()で送ると、デバイス側が「まだ続きがある」と
    // 解釈して確定させず止まってしまう既知の問題がある(PCのシリアル
    // ドライバはこれを吸収してくれるが、Androidの生USB通信では露呈しやすい)。
    // そのため必ず64バイト未満の単位に分割して送る。
    private val USB_WRITE_CHUNK = 32

    private fun writeAll(bytes: ByteArray, timeoutMs: Int = 5000) {
        var offset = 0
        while (offset < bytes.size) {
            val end = minOf(offset + USB_WRITE_CHUNK, bytes.size)
            port.write(bytes.copyOfRange(offset, end), timeoutMs)
            offset = end
        }
    }

    /** ちょうどn バイト読めるまで待つ(タイムアウトしたら例外)。 */
    private fun readExact(n: Int, timeoutMs: Long): ByteArray {
        val result = ByteArray(n)
        val deadline = System.currentTimeMillis() + timeoutMs
        for (i in 0 until n) {
            val remaining = deadline - System.currentTimeMillis()
            if (remaining <= 0) {
                throw IOException("応答なし(タイムアウト)。$i/$n バイトのみ受信")
            }
            val b = rxQueue.poll(remaining, TimeUnit.MILLISECONDS)
                ?: throw IOException("応答なし(タイムアウト)。$i/$n バイトのみ受信")
            result[i] = b
        }
        return result
    }

    private fun readByte(timeoutMs: Long): Int {
        return readExact(1, timeoutMs)[0].toInt() and 0xFF
    }

    // ------------------------------------------------------------ プロトコル

    fun reset() {
        log("SPC700をリセットしてready待ち...")
        writeAll(byteArrayOf(CMD_RESET.toByte()))
        val b = readByte(5000)
        if (b != ACK_RESET) throw IOException("想定外の応答: 0x%02X (期待値 0x%02X)".format(b, ACK_RESET))
        log("SPC700 ready.")
    }

    fun setAddress(addr: Int, continueTransfer: Boolean) {
        log("→ CMD_SETADDR addr=\$${"%04X".format(addr)} continue=$continueTransfer を送信...")
        writeAll(
            byteArrayOf(
                CMD_SETADDR.toByte(),
                (addr and 0xFF).toByte(),
                ((addr shr 8) and 0xFF).toByte(),
                (if (continueTransfer) 1 else 0).toByte(),
            )
        )
        log("  送信完了、応答待ち...")
        val b = readByte(5000)
        log("  応答受信: 0x%02X".format(b))
        if (b == MARKER_TIMEOUT) {
            val rest = readExact(4, 5000)
            if ((rest[0].toInt() and 0xFF) == 0xFF && (rest[1].toInt() and 0xFF) == 0xFF) {
                throw IOException("SETADDRがタイムアウト: addr=$%04X".format(addr))
            }
            throw IOException("SETADDR異常応答: ${rest.joinToString()}")
        }
        if (b != ACK_SETADDR) {
            throw IOException("想定外の応答: 0x%02X (期待値 0x%02X)".format(b, ACK_SETADDR))
        }
    }

    fun sendBytes(data: ByteArray) {
        val length = data.size
        log("→ CMD_SENDBYTES len=$length を送信...")
        writeAll(
            byteArrayOf(
                CMD_SENDBYTES.toByte(),
                (length and 0xFF).toByte(),
                ((length shr 8) and 0xFF).toByte(),
            )
        )
        log("  送信完了、診断応答待ち...")

        val diag = readExact(3, 5000)
        log("  診断応答受信: ${diag.joinToString { "%02X".format(it) }}")
        if ((diag[0].toInt() and 0xFF) != 0xAB) {
            throw IOException("len診断応答が異常: ${diag.joinToString()} (送った長さ=$length)")
        }
        val echoedLen = (diag[1].toInt() and 0xFF) or ((diag[2].toInt() and 0xFF) shl 8)
        if (echoedLen != length) {
            throw IOException("lenが化けた! 送った長さ=$length, Arduinoが受け取った長さ=$echoedLen")
        }

        // PING_INTERVALバイトずつ送って「まとめて1回だけ」確認応答を待つ。
        // (詳細は spc_play.py の send_bytes() コメント参照。1バイトごとの
        // 往復方式はUSBシリアルの往復遅延が支配的になり大幅に遅かった)
        var pos = 0
        var firstChunk = true
        while (pos < length) {
            checkCancel()
            val chunkLen = minOf(PING_INTERVAL, length - pos)
            if (firstChunk) {
                log("  1回目のチャンク($chunkLen バイト)を送信...")
                firstChunk = false
            }
            writeAll(data.copyOfRange(pos, pos + chunkLen))
            if (pos == 0) log("  1回目のチャンク送信完了、応答待ち...")

            val marker = readByte(5000)
            if (pos == 0) log("  1回目の応答受信: 0x%02X".format(marker))
            if (marker == MARKER_TIMEOUT) {
                val rest = readExact(4, 5000)
                val idx = (rest[0].toInt() and 0xFF) or ((rest[1].toInt() and 0xFF) shl 8)
                throw IOException(
                    "転送中にタイムアウト: バイト位置 $idx/$length で停止。" +
                        "送信した値=0x%02X, 実際に読めた値=0x%02X".format(rest[2], rest[3])
                )
            }
            if (marker != MARKER_BYTE_OK) {
                throw IOException("想定外の応答バイト: 0x%02X (進捗=$pos/$length)".format(marker))
            }

            pos += chunkLen
            val total = if (totalBytes > 0) totalBytes else length
            onProgress(doneBytes + pos, total)
        }

        val final = readByte(5000)
        if (final != ACK_SENDBYTES) {
            throw IOException("最終応答が想定外: 0x%02X".format(final))
        }
    }

    fun writeBlock(addr: Int, data: ByteArray) {
        setAddress(addr, true)
        sendBytes(data)
    }

    fun jumpTo(addr: Int) {
        setAddress(addr, false)
    }

    fun readPort(portNum: Int): Int {
        writeAll(byteArrayOf(CMD_READPORT.toByte(), portNum.toByte()))
        val resp = readExact(2, 3000)
        if ((resp[0].toInt() and 0xFF) != 0x04) {
            throw IOException("read_port応答が異常: ${resp.joinToString()}")
        }
        return resp[1].toInt() and 0xFF
    }

    /** TDA7053AのVC1/VC2へつながるPWM(Arduino D10)のデューティ比を設定する(0-255)。 */
    fun setVolume(duty: Int): Int {
        val d = duty.coerceIn(0, 255)
        writeAll(byteArrayOf(CMD_SETVOLUME.toByte(), d.toByte()))
        val resp = readExact(2, 3000)
        if ((resp[0].toInt() and 0xFF) != CMD_SETVOLUME) {
            throw IOException("set_volume応答が異常: ${resp.joinToString()}")
        }
        return resp[1].toInt() and 0xFF
    }
}
