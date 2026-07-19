package org.szaghi.harp

import android.Manifest
import android.content.Intent
import android.hardware.SensorManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/**
 * Phase-2 minimal horizon wizard: live true-az/alt readout, tap-to-record
 * vertices, polar preview, .hrz export via the share sheet.
 * (Camera AR overlay: phase 2b.)
 */
@Composable
fun HorizonScreen(vm: HorizonViewModel) {
    val context = LocalContext.current
    var status by remember { mutableStateOf("") }
    var cameraOn by remember { mutableStateOf(false) }
    var falseColor by remember { mutableStateOf(false) }
    var cameraGranted by remember { mutableStateOf(false) }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        vm.refreshLocation()
        cameraGranted = grants[Manifest.permission.CAMERA] == true ||
            androidx.core.content.ContextCompat.checkSelfPermission(
                context, Manifest.permission.CAMERA
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED
    }

    DisposableEffect(Unit) {
        vm.startSensors()
        permissionLauncher.launch(
            arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION,
                Manifest.permission.CAMERA,
            )
        )
        onDispose { vm.stopSensors() }
    }

    Column(Modifier.fillMaxSize()) {
        // scrollable info region
        Column(
            Modifier
                .weight(1f)
                .padding(16.dp)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
        ) {
            Text(
                "Az %.1f°  Alt %.1f°".format(vm.azimuthTrue, vm.altitude),
                style = MaterialTheme.typography.headlineMedium,
            )
            Text(
                "true north (decl %+.1f°) | compass: %s".format(
                    vm.declination,
                    when (vm.sensorAccuracy) {
                        SensorManager.SENSOR_STATUS_ACCURACY_HIGH -> "good"
                        SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM -> "fair"
                        SensorManager.SENSOR_STATUS_ACCURACY_LOW -> "poor - do a figure-8"
                        else -> "UNRELIABLE - recalibrate"
                    },
                ),
                style = MaterialTheme.typography.bodySmall,
            )
            Text(
                vm.latitude?.let {
                    "site %.5f, %.5f, %.0f m".format(it, vm.longitude, vm.elevation ?: 0.0)
                } ?: "no GPS fix - declination assumed 0, tap GPS below",
                style = MaterialTheme.typography.bodySmall,
            )
            if (vm.locationStatus.isNotEmpty()) {
                Text(vm.locationStatus, style = MaterialTheme.typography.bodySmall)
            }
            Text(
                "Sanity check: camera at the horizon should read Alt 0, zenith +90.",
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.height(12.dp))

            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
            ) {
                Text("Camera", style = MaterialTheme.typography.bodySmall)
                Switch(checked = cameraOn, onCheckedChange = { cameraOn = it })
                if (cameraOn) {
                    Text("False color", style = MaterialTheme.typography.bodySmall)
                    Switch(checked = falseColor, onCheckedChange = { falseColor = it })
                }
            }
            if (cameraOn && cameraGranted) {
                // tap anywhere on the preview = capture the crosshair direction
                CameraReticle(
                    vm, falseColor,
                    Modifier.fillMaxWidth().aspectRatio(3f / 4f),
                    onTap = { vm.addVertex() },
                )
            } else {
                if (cameraOn) {
                    Text(
                        "camera permission not granted",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                PolarPreview(vm.vertices, Modifier.fillMaxWidth().aspectRatio(1f))
            }
            Spacer(Modifier.height(8.dp))

            Text(
                "${vm.vertices.size} vertices: " +
                    vm.vertices.joinToString { "(%.0f°, %.0f°)".format(it.azTrue, it.alt) },
                style = MaterialTheme.typography.bodySmall,
            )
            if (status.isNotEmpty()) Text(status, style = MaterialTheme.typography.bodySmall)
        }

        // pinned bottom action bar: one-hand reach on tall phones
        Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
            Button(
                onClick = { vm.addVertex() },
                modifier = Modifier.fillMaxWidth().height(64.dp),
            ) { Text("Add vertex", style = MaterialTheme.typography.titleLarge) }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { vm.addWallEdge() },
                    modifier = Modifier.weight(1f),
                ) { Text("Wall 90°") }
                OutlinedButton(
                    onClick = { vm.removeLast() },
                    modifier = Modifier.weight(1f),
                ) { Text("Undo") }
                OutlinedButton(
                    onClick = { vm.requestFix() },
                    modifier = Modifier.weight(1f),
                ) { Text("GPS") }
                Button(
                    enabled = vm.vertices.size >= 2,
                    modifier = Modifier.weight(1f),
                    onClick = {
                        // never crash on export: surface errors in the status line
                        runCatching {
                            val (file, problems) = vm.exportHrz()
                            status = if (problems.isEmpty()) "exported ${file.name}"
                            else "exported with warnings: ${problems.joinToString()}"
                            val uri = FileProvider.getUriForFile(
                                context, "${context.packageName}.fileprovider", file,
                            )
                            val share = Intent(Intent.ACTION_SEND).apply {
                                type = "text/plain"
                                putExtra(Intent.EXTRA_STREAM, uri)
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            context.startActivity(
                                Intent.createChooser(share, "Share horizon.hrz")
                            )
                        }.onFailure { status = "export failed: ${it.message}" }
                    },
                ) { Text("Export") }
            }
        }
    }
}

/** Polar plot of the recorded skyline: N up, E right, zenith at the center. */
@Composable
fun PolarPreview(vertices: List<Vertex>, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        val radius = min(size.width, size.height) / 2f * 0.9f
        val center = Offset(size.width / 2f, size.height / 2f)
        // horizon ring + altitude rings every 30 deg
        for (alt in intArrayOf(0, 30, 60)) {
            drawCircle(
                color = Color.LightGray,
                radius = radius * (90 - alt) / 90f,
                center = center,
                style = androidx.compose.ui.graphics.drawscope.Stroke(width = 2f),
            )
        }
        fun toOffset(azDeg: Float, altDeg: Float): Offset {
            val r = radius * (90f - altDeg.coerceIn(0f, 90f)) / 90f
            val a = Math.toRadians(azDeg.toDouble() - 90.0) // N up, E right
            return Offset(
                center.x + (r * cos(a)).toFloat(),
                center.y + (r * sin(a)).toFloat(),
            )
        }
        val sorted = vertices.sortedBy { it.azTrue }
        sorted.zipWithNext().forEach { (a, b) ->
            drawLine(Color(0xFF2E8B57), toOffset(a.azTrue, a.alt), toOffset(b.azTrue, b.alt), 4f)
        }
        sorted.forEach { v ->
            drawCircle(Color(0xFF1F4FD8), radius = 8f, center = toOffset(v.azTrue, v.alt))
        }
    }
}
