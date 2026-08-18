package com.shvc.soundplayer

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.ListView
import android.widget.ProgressBar
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.documentfile.provider.DocumentFile
import com.hoho.android.usbserial.driver.UsbSerialDriver
import com.hoho.android.usbserial.driver.UsbSerialPort
import com.hoho.android.usbserial.driver.UsbSerialProber
import java.io.IOException

class MainActivity : AppCompatActivity() {

    companion object {
        private const val ACTION_USB_PERMISSION = "com.shvc.soundplayer.USB_PERMISSION"
        private const val PREFS_NAME = "shvc_prefs"
        private const val PREF_FOLDER_URI = "spc_folder_uri"
    }

    private data class SpcEntry(val uri: Uri, val name: String)

    private lateinit var prefs: SharedPreferences

    private lateinit var btnConnect: Button
    private lateinit var tvConnStatus: TextView
    private lateinit var btnPickFolder: Button
    private lateinit var tvFolderPath: TextView
    private lateinit var listPlaylist: ListView
    private lateinit var btnPlay: Button
    private lateinit var btnStop: Button
    private lateinit var progressTransfer: ProgressBar
    private lateinit var seekDspVolume: SeekBar
    private lateinit var tvDspVolume: TextView
    private lateinit var checkAmp: CheckBox
    private lateinit var seekAmpVolume: SeekBar
    private lateinit var tvAmpVolume: TextView
    private lateinit var tvLog: TextView

    private var usbPort: UsbSerialPort? = null
    private var controller: SpcController? = null

    private var playlist: List<SpcEntry> = emptyList()
    private lateinit var playlistAdapter: ArrayAdapter<String>
    private var selectedIndex: Int = -1

    private var playThread: Thread? = null
    @Volatile private var cancelRequested: Boolean = false

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action != ACTION_USB_PERMISSION) return
            val device = intent.getUsbDeviceExtra()
            if (intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)) {
                if (device != null) connectToDevice(device)
            } else {
                appendLog("USB権限が拒否されました。")
            }
        }
    }

    private val folderPickerLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri: Uri? ->
            if (uri != null) {
                contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                )
                prefs.edit().putString(PREF_FOLDER_URI, uri.toString()).apply()
                loadFolder(uri)
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        btnConnect = findViewById(R.id.btnConnect)
        tvConnStatus = findViewById(R.id.tvConnStatus)
        btnPickFolder = findViewById(R.id.btnPickFolder)
        tvFolderPath = findViewById(R.id.tvFolderPath)
        listPlaylist = findViewById(R.id.listPlaylist)
        btnPlay = findViewById(R.id.btnPlay)
        btnStop = findViewById(R.id.btnStop)
        progressTransfer = findViewById(R.id.progressTransfer)
        seekDspVolume = findViewById(R.id.seekDspVolume)
        tvDspVolume = findViewById(R.id.tvDspVolume)
        checkAmp = findViewById(R.id.checkAmp)
        seekAmpVolume = findViewById(R.id.seekAmpVolume)
        tvAmpVolume = findViewById(R.id.tvAmpVolume)
        tvLog = findViewById(R.id.tvLog)

        playlistAdapter = ArrayAdapter(this, android.R.layout.simple_list_item_activated_1, mutableListOf())
        listPlaylist.adapter = playlistAdapter
        listPlaylist.choiceMode = ListView.CHOICE_MODE_SINGLE
        listPlaylist.setOnItemClickListener { _, _, position, _ -> selectedIndex = position }

        btnConnect.setOnClickListener { requestUsbConnection() }
        btnPickFolder.setOnClickListener { folderPickerLauncher.launch(null) }
        btnPlay.setOnClickListener { onPlayClicked() }
        btnStop.setOnClickListener { onStopClicked() }

        seekDspVolume.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar, progress: Int, fromUser: Boolean) {
                val factor = 1.0 + progress * 0.1
                tvDspVolume.text = "%.2f倍".format(factor)
            }
            override fun onStartTrackingTouch(seekBar: SeekBar) {}
            override fun onStopTrackingTouch(seekBar: SeekBar) {}
        })

        seekAmpVolume.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar, progress: Int, fromUser: Boolean) {
                tvAmpVolume.text = progress.toString()
            }
            override fun onStartTrackingTouch(seekBar: SeekBar) {}
            override fun onStopTrackingTouch(seekBar: SeekBar) {}
        })

        checkAmp.setOnCheckedChangeListener { _, checked -> seekAmpVolume.isEnabled = checked }

        val filter = IntentFilter(ACTION_USB_PERMISSION)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(usbReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(usbReceiver, filter)
        }

        // 前回選択したSPCフォルダを復元する
        prefs.getString(PREF_FOLDER_URI, null)?.let { s ->
            try {
                loadFolder(Uri.parse(s))
            } catch (e: Exception) {
                appendLog("フォルダの復元に失敗: ${e.message}")
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        try {
            unregisterReceiver(usbReceiver)
        } catch (e: IllegalArgumentException) {
            // 未登録なら何もしない
        }
        try {
            controller?.stopIo()
        } catch (e: Exception) {
            // 終了時なので無視してよい
        }
        try {
            usbPort?.close()
        } catch (e: IOException) {
            // 終了時なので無視してよい
        }
    }

    private fun Intent.getUsbDeviceExtra(): UsbDevice? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        } else {
            @Suppress("DEPRECATION")
            getParcelableExtra(UsbManager.EXTRA_DEVICE)
        }
    }

    // ---------------------------------------------------------------- USB

    private fun requestUsbConnection() {
        val usbManager = getSystemService(Context.USB_SERVICE) as UsbManager
        val drivers = UsbSerialProber.getDefaultProber().findAllDrivers(usbManager)
        if (drivers.isEmpty()) {
            appendLog("USBシリアルデバイスが見つかりません。Arduinoが接続されているか確認してください。")
            return
        }
        val device = drivers[0].device

        if (usbManager.hasPermission(device)) {
            connectToDevice(device)
            return
        }

        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
        // Android 14(API 34)以降、暗黙的インテント(パッケージ未指定)に
        // FLAG_MUTABLEを付けたPendingIntentはセキュリティ上禁止されている。
        // 自分のアプリ宛てだと明示するため setPackage(packageName) を付ける。
        val intent = Intent(ACTION_USB_PERMISSION).setPackage(packageName)
        val permissionIntent = PendingIntent.getBroadcast(this, 0, intent, flags)
        usbManager.requestPermission(device, permissionIntent)
    }

    private fun connectToDevice(device: UsbDevice) {
        val usbManager = getSystemService(Context.USB_SERVICE) as UsbManager
        val driver: UsbSerialDriver? = UsbSerialProber.getDefaultProber()
            .findAllDrivers(usbManager)
            .firstOrNull { it.device.deviceId == device.deviceId }
        if (driver == null) {
            appendLog("対応するUSBシリアルドライバが見つかりません。")
            return
        }
        val connection = usbManager.openDevice(driver.device)
        if (connection == null) {
            appendLog("USBデバイスを開けませんでした。権限を確認してください。")
            return
        }
        val port = driver.ports[0]
        try {
            port.open(connection)
            port.setParameters(
                SpcController.BAUD_RATE, 8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE
            )
            // PC側(pyserial)は接続時に自動でDTR/RTSを立てるが、Android側の
            // このライブラリでは明示的に立てないと、小さいコマンド(1バイト
            // 応答など)は偶然通っても、まとまったデータ転送が不安定になる
            // ことがある。
            try {
                port.setDTR(true)
                port.setRTS(true)
            } catch (e: UnsupportedOperationException) {
                // DTR/RTS制御に対応していないチップの場合は無視してよい
            }
        } catch (e: IOException) {
            appendLog("接続エラー: ${e.message}")
            return
        }
        usbPort = port
        controller = SpcController(port, log = ::appendLogAsync, onProgress = ::updateProgress)
        tvConnStatus.text = "接続済み: ${driver.javaClass.simpleName}"
        appendLog("USB接続しました。")
    }

    // ------------------------------------------------------------- フォルダ

    private fun loadFolder(treeUri: Uri) {
        val tree = DocumentFile.fromTreeUri(this, treeUri)
        if (tree == null) {
            appendLog("フォルダを開けませんでした。")
            return
        }
        val entries = tree.listFiles()
            .filter { it.isFile && (it.name?.lowercase()?.endsWith(".spc") == true) }
            .mapNotNull { f -> f.name?.let { SpcEntry(f.uri, it) } }
            .sortedBy { it.name }

        playlist = entries
        playlistAdapter.clear()
        playlistAdapter.addAll(entries.map { it.name })
        playlistAdapter.notifyDataSetChanged()
        tvFolderPath.text = treeUri.path ?: treeUri.toString()
        appendLog("${entries.size}件の.spcファイルを読み込みました。")
    }

    // ------------------------------------------------------------- 再生

    private fun onPlayClicked() {
        val ctl = controller
        if (ctl == null) {
            appendLog("先にUSB接続してください。")
            return
        }
        if (playThread?.isAlive == true) {
            appendLog("転送中です。完了までお待ちください。")
            return
        }
        if (playlist.isEmpty()) {
            appendLog("プレイリストが空です。SPCフォルダを選択してください。")
            return
        }
        val index = if (selectedIndex in playlist.indices) selectedIndex else 0
        val entry = playlist[index]
        selectedIndex = index
        listPlaylist.setItemChecked(index, true)

        val factor = 1.0 + seekDspVolume.progress * 0.1
        val ampVolume = if (checkAmp.isChecked) seekAmpVolume.progress else null

        cancelRequested = false
        progressTransfer.progress = 0
        setBusy(true)
        appendLog("=== 再生開始: ${entry.name} ===")

        playThread = Thread {
            try {
                val bytes = contentResolver.openInputStream(entry.uri)?.use { it.readBytes() }
                    ?: throw IOException("ファイルを開けませんでした")
                val spc = SpcFile(bytes, entry.name)
                ctl.setCancelCheck { cancelRequested }
                Player.play(ctl, spc, volumeFactor = factor, ampVolume = ampVolume, log = ::appendLogAsync)
                runOnUiThread {
                    progressTransfer.progress = 100
                    setBusy(false)
                }
            } catch (e: SpcController.TransferCancelled) {
                runOnUiThread {
                    appendLog("転送を中止しました。")
                    setBusy(false)
                }
            } catch (e: Exception) {
                runOnUiThread {
                    appendLog("エラー: ${e.message}")
                    Toast.makeText(this, "再生に失敗しました: ${e.message}", Toast.LENGTH_LONG).show()
                    setBusy(false)
                }
            }
        }
        playThread?.start()
    }

    private fun onStopClicked() {
        val ctl = controller
        if (ctl == null) {
            appendLog("先にUSB接続してください。")
            return
        }
        if (playThread?.isAlive == true) {
            cancelRequested = true
            appendLog("転送の中止を要求しました...")
            return
        }
        Thread {
            try {
                Player.stop(ctl, log = ::appendLogAsync)
            } catch (e: Exception) {
                runOnUiThread { appendLog("停止に失敗: ${e.message}") }
            }
        }.start()
    }

    private fun setBusy(busy: Boolean) {
        btnPlay.isEnabled = !busy
        btnConnect.isEnabled = !busy
        btnPickFolder.isEnabled = !busy
    }

    // --------------------------------------------------------- UIヘルパー

    private fun appendLog(msg: String) {
        tvLog.append("$msg\n")
    }

    /** バックグラウンドスレッドから安全に呼べるログ出力。 */
    private fun appendLogAsync(msg: String) {
        runOnUiThread { appendLog(msg) }
    }

    private fun updateProgress(done: Int, total: Int) {
        if (total <= 0) return
        val pct = (done * 100L / total).toInt().coerceIn(0, 100)
        runOnUiThread { progressTransfer.progress = pct }
    }
}
