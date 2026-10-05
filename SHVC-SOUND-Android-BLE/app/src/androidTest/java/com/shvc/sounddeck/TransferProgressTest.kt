package com.shvc.sounddeck

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.isRoot
import org.junit.Rule
import org.junit.Test

class TransferProgressTest {
    @get:Rule val compose=createComposeRule()
    @Test fun switchingToChipTransferKeepsDrawAndSemanticsSafe() {
        val progress=mutableStateOf<Float?>(0.95f)
        compose.setContent { DeckTheme { Column { TransferProgress(progress.value) } } }
        repeat(20) {
            compose.runOnUiThread { progress.value=1f }
            compose.runOnUiThread { progress.value=null }
            compose.onAllNodes(isRoot()).fetchSemanticsNodes()
            compose.waitForIdle()
            compose.runOnUiThread { progress.value=0.25f }
            compose.waitForIdle()
        }
    }
}
