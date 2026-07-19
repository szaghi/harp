package org.szaghi.harp

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.TimeZone

/**
 * Phase-1 spike: one button that proves numpy + astropy + astroplan + the
 * shared harp core run on this phone by computing tonight's twilight.
 */
@Composable
fun SpikeScreen() {
    var result by remember { mutableStateOf("Press the button to run the on-device astro stack.") }
    var running by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        Modifier
            .padding(16.dp)
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
    ) {
        Button(
            enabled = !running,
            onClick = {
                running = true
                result = "Computing tonight's darkness window on-device..."
                scope.launch {
                    result = withContext(Dispatchers.IO) {
                        try {
                            PyBridge.py.getModule("spike")
                                // Castelli Romani as the reference position;
                                // the wizard tab uses the real GPS fix
                                .callAttr(
                                    "twilight_summary",
                                    41.738026, 12.889862, 300.0,
                                    TimeZone.getDefault().id,
                                )
                                .toString()
                        } catch (e: Exception) {
                            "SPIKE FAILED:\n${e.message}"
                        }
                    }
                    running = false
                }
            },
        ) { Text("Run astropy spike") }
        Spacer(Modifier.height(16.dp))
        Text(result, style = MaterialTheme.typography.bodyMedium)
    }
}
