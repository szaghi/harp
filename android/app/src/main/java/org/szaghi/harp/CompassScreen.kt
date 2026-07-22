package org.szaghi.harp

import android.graphics.Paint
import android.hardware.SensorManager
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Polar-alignment compass tab.
 *
 * A live compass rose (true north, declination already applied) with the
 * visible celestial pole marked on it, plus a plain-language "turn / tilt"
 * delta from where the phone points now to the pole. Aim the phone back
 * (camera) along the mount's polar axis; drive the delta to zero for a rough
 * mechanical polar alignment before drift or plate-solve refinement.
 *
 * All angles come from [CompassViewModel]; nothing here calls the Python
 * core. Accuracy is limited by the magnetometer (typically 1-2 deg after a
 * good calibration) — enough to get the pole into a finder or wide field,
 * not a substitute for drift/plate-solve alignment.
 */
@Composable
fun CompassScreen(vm: CompassViewModel) {
    DisposableEffect(Unit) {
        vm.startSensors()
        onDispose { vm.stopSensors() }
    }

    Column(
        Modifier
            .padding(16.dp)
            .fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            if (vm.northern) "North celestial pole" else "South celestial pole",
            style = MaterialTheme.typography.titleMedium,
        )
        Text(
            calibrationHint(vm.sensorAccuracy),
            style = MaterialTheme.typography.bodySmall,
            color = calibrationColor(vm.sensorAccuracy),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))

        CompassRose(vm, Modifier.fillMaxWidth().aspectRatio(1f))

        if (vm.gyroAvailable) {
            Spacer(Modifier.height(12.dp))
            HoldControl(vm)
        }

        Spacer(Modifier.height(12.dp))
        GuidancePanel(vm)
    }
}

/**
 * The gyro-hold ("INS") control. Lock a clean heading away from the mount,
 * then walk the phone in — the held heading rides the gyro and ignores the
 * magnetometer while the mount's steel would otherwise corrupt it.
 */
@Composable
private fun HoldControl(vm: CompassViewModel) {
    if (vm.holding) {
        val stale = vm.heldAtAccuracy != SensorManager.SENSOR_STATUS_ACCURACY_HIGH
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                "🔒 heading held on gyro — %.0f s".format(vm.holdElapsedS),
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
            )
            Text(
                if (stale) {
                    "locked while the compass was NOT calibrated — the held value " +
                        "is only as good as that reading"
                } else {
                    "magnetometer ignored — walk the phone to the mount, keep it on " +
                        "the pole, keep tilt steady"
                },
                style = MaterialTheme.typography.bodySmall,
                color = if (stale) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurface,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(6.dp))
            OutlinedButton(onClick = { vm.releaseHold() }) { Text("Release") }
        }
    } else {
        val ready = vm.sensorAccuracy == SensorManager.SENSOR_STATUS_ACCURACY_HIGH
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Button(
                onClick = { vm.lockHeading() },
                colors = if (ready) ButtonDefaults.buttonColors()
                else ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer,
                ),
            ) { Text(if (ready) "Lock heading" else "Lock anyway (uncalibrated)") }
            Text(
                "aim at the pole clear of the mount, lock, then walk the phone in",
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
            )
        }
    }
}

/**
 * The rose is drawn heading-up: the fixed triangle at the top is the phone's
 * current pointing, and the card rotates beneath it. The pole pip sits at the
 * pole azimuth; when it reaches the top index the phone points at (or over)
 * the pole in azimuth. The whole card counter-rotates by roll so N stays
 * where the world's north is even when the phone is tilted in-plane.
 */
@Composable
private fun CompassRose(vm: CompassViewModel, modifier: Modifier) {
    val onSurface = MaterialTheme.colorScheme.onSurface
    val accent = MaterialTheme.colorScheme.primary
    // The pole marker must be the boldest thing on the rose AND stay on-hue
    // in every theme — the red night scheme collapses all accents to red, so
    // it must come from a defined token. `tertiary` is left unset by the
    // theme's scheme() builder (falls back to Material's grey/purple), which
    // is exactly the off-palette bug; `primary` is the accent every scheme
    // defines (red in night mode).
    val poleColor = MaterialTheme.colorScheme.primary
    val labelPaint = remember(onSurface) {
        Paint().apply {
            color = onSurface.toArgb()
            textSize = 40f
            textAlign = Paint.Align.CENTER
            isAntiAlias = true
        }
    }
    val cardinalPaint = remember(accent) {
        Paint().apply {
            color = accent.toArgb()
            textSize = 56f
            textAlign = Paint.Align.CENTER
            isFakeBoldText = true
            isAntiAlias = true
        }
    }
    val poleTextPaint = remember(poleColor) {
        Paint().apply {
            color = poleColor.toArgb()
            textSize = 32f
            textAlign = Paint.Align.CENTER
            isAntiAlias = true
        }
    }

    Canvas(modifier) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val r = min(cx, cy) * 0.86f

        // fixed top index = where the phone points now (the "you are here");
        // it turns to the pole colour while the gyro hold is active
        drawTriangle(Offset(cx, cy - r - 2f), 22f, if (vm.holding) poleColor else accent)

        // The card is heading-up: a bearing B sits at screen angle
        // (B - heading), measured clockwise from the top index. Roll rotates
        // the whole card so the world stays level under an in-plane tilt.
        val heading = vm.azimuthTrue
        fun screenAngleDeg(bearing: Float): Float = bearing - heading - vm.roll

        fun dirFor(bearing: Float, radius: Float): Offset {
            val a = Math.toRadians((screenAngleDeg(bearing) - 90.0))
            return Offset(cx + radius * cos(a).toFloat(), cy + radius * sin(a).toFloat())
        }

        // tick ring
        for (deg in 0 until 360 step 5) {
            val major = deg % 45 == 0
            val outer = dirFor(deg.toFloat(), r)
            val inner = dirFor(deg.toFloat(), r - (if (major) 26f else 14f))
            drawLine(
                onSurface.copy(alpha = if (major) 0.9f else 0.55f),
                inner, outer, if (major) 4f else 2f,
            )
        }

        // cardinal letters
        listOf(0f to "N", 90f to "E", 180f to "S", 270f to "W").forEach { (b, s) ->
            val p = dirFor(b, r - 62f)
            drawContext.canvas.nativeCanvas.drawText(
                s, p.x, p.y + 20f,
                if (s == "N") cardinalPaint else labelPaint,
            )
        }

        // pole pip on the rose + a spoke to it, at the pole azimuth
        val poleTip = dirFor(vm.poleAzimuth, r - 30f)
        drawLine(poleColor, Offset(cx, cy), poleTip, 5f)
        drawCircle(poleColor, 16f, poleTip)
        if (vm.northern) {
            drawContext.canvas.nativeCanvas.drawText(
                "Polaris", poleTip.x, poleTip.y - 26f, poleTextPaint,
            )
        }

        // hub
        drawCircle(onSurface, 8f, Offset(cx, cy))
    }
}

/** Plain-language guidance: how to swing/tilt from here to the pole. */
@Composable
private fun GuidancePanel(vm: CompassViewModel) {
    if (!vm.hasFix) {
        Text(
            "waiting for a GPS fix — the pole altitude equals your latitude, " +
                "so a position is needed. Open the Horizon or Plan tab once to " +
                "acquire a fix, then return.",
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
        return
    }

    // signed azimuth error, -180..180: + means the pole is to the RIGHT
    var dAz = vm.poleAzimuth - vm.azimuthTrue
    if (dAz > 180f) dAz -= 360f
    if (dAz < -180f) dAz += 360f
    val dAlt = vm.poleAltitude - vm.altitude

    val turn = if (abs(dAz) < 0.5f) "on the pole azimuth" else {
        "turn ${abs(dAz).roundToInt()}° ${if (dAz > 0) "right (E)" else "left (W)"}"
    }
    val tilt = if (abs(dAlt) < 0.5f) "at pole altitude" else {
        "tilt ${abs(dAlt).roundToInt()}° ${if (dAlt > 0) "up" else "down"}"
    }
    val onTarget = abs(dAz) < 2f && abs(dAlt) < 2f

    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            if (onTarget) "▲ on the pole" else "$turn, $tilt",
            style = MaterialTheme.typography.titleLarge,
            color = if (onTarget) MaterialTheme.colorScheme.primary
            else MaterialTheme.colorScheme.onSurface,
            fontFamily = FontFamily.Monospace,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceEvenly,
        ) {
            Readout("heading", "%.1f°".format(vm.azimuthTrue))
            Readout("altitude", "%+.1f°".format(vm.altitude))
            Readout("pole alt", "%.1f°".format(vm.poleAltitude))
        }
        Spacer(Modifier.height(6.dp))
        Text(
            "declination %+.1f° applied • magnetometer ~1-2° — get the pole into a "
                .format(vm.declination) +
                "finder, then refine by drift or plate-solve",
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun Readout(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, style = MaterialTheme.typography.titleMedium, fontFamily = FontFamily.Monospace)
        Text(label, style = MaterialTheme.typography.bodySmall)
    }
}

private fun calibrationHint(accuracy: Int): String = when (accuracy) {
    SensorManager.SENSOR_STATUS_ACCURACY_HIGH -> "compass calibrated"
    SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM -> "compass OK — a figure-8 wave sharpens it"
    SensorManager.SENSOR_STATUS_ACCURACY_LOW ->
        "compass low — wave the phone in a figure-8, away from metal"
    else -> "compass uncalibrated — wave in a figure-8, clear of metal/magnets"
}

@Composable
private fun calibrationColor(accuracy: Int): Color = when (accuracy) {
    SensorManager.SENSOR_STATUS_ACCURACY_HIGH -> MaterialTheme.colorScheme.primary
    SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM -> MaterialTheme.colorScheme.onSurface
    else -> MaterialTheme.colorScheme.error
}

private fun DrawScope.drawTriangle(apex: Offset, sizePx: Float, color: Color) {
    val path = Path().apply {
        moveTo(apex.x, apex.y)
        lineTo(apex.x - sizePx * 0.6f, apex.y - sizePx)
        lineTo(apex.x + sizePx * 0.6f, apex.y - sizePx)
        close()
    }
    drawPath(path, color)
}
