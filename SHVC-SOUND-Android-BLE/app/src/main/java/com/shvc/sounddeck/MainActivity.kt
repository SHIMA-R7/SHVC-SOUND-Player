package com.shvc.sounddeck

import android.content.Intent
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.flow.first
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.SystemBarStyle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.*

class MainActivity: ComponentActivity() {
    private val model: DeckViewModel by viewModels()
    private val permissions=registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        if(result.values.all { it }) model.scan() else model.report("近くのデバイスへのアクセスを許可すると接続できます")
    }
    private val picker=registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if(uris.isNotEmpty()) model.addFiles(uris)
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(statusBarStyle=SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle=SystemBarStyle.dark(android.graphics.Color.TRANSPARENT))
        setContent { DeckTheme { SoundDeck(model,::requestScan,{ picker.launch(arrayOf("*/*")) }) } }
        handlePlaylistIntent(intent)
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handlePlaylistIntent(intent)
    }
    private fun handlePlaylistIntent(request: Intent) {
        if(request.action!="com.shvc.sounddeck.action.PLAY_PLAYLIST") return
        val address=request.getStringExtra("deviceAddress") ?: return
        if(!android.bluetooth.BluetoothAdapter.checkBluetoothAddress(address)) return
        request.action=Intent.ACTION_MAIN
        request.removeExtra("deviceAddress")
        lifecycleScope.launch {
            try {
                if(!model.ble.link.value.ready) model.connect(address)
                withTimeout(45000) {
                    model.ble.link.first { it.ready }
                    model.ui.first { !it.busy }
                }
                model.startPlaylist()
            } catch(e: kotlinx.coroutines.CancellationException) { throw e }
            catch(e: Throwable) { model.report(e.message ?: "再生リストを開始できません") }
        }
    }
    private fun requestScan() {
        val required=if(Build.VERSION.SDK_INT>=31) arrayOf(Manifest.permission.BLUETOOTH_SCAN,Manifest.permission.BLUETOOTH_CONNECT)
        else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        if(required.all { checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED }) model.scan()
        else permissions.launch(required)
    }
    override fun onStop() { model.releaseNotes(); super.onStop() }
}
