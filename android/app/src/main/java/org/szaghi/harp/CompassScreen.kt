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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Polar-alignment compass tab.
 *
 * Built for one workflow: rough-align the mount in TWILIGHT, before Polaris is
 * visible, then hand off to N.I.N.A. TPPA once it rises. Stage 1 is a live
 * compass rose for finding the pole by eye; stage 2 is the assistant used with
 * the phone fixed to the mount, giving bolt corrections plus a bullseye.
 *
 * Accuracy is the magnetometer's (1-2 deg after a good calibration). Against a
 * polar scope's ~5-8 deg field that is genuinely sufficient for this job — the
 * arcminute work belongs to TPPA, not here.
 */
@Composable
fun CompassScreen(vm: CompassViewModel) {
    DisposableEffect(Unit) {
        vm.startSensors()
        onDispose { vm.stopSensors() }
    }
    // Two stages. COARSE is the free-standing compass rose (find the pole by
    // eye, phone in hand); ALIGN is the assistant used with the phone fixed to
    // the mount, driving the axis onto the pole in twilight. Same sensors,
    // different jobs — kept apart so the rose is not mistaken for guidance.
    var stage by rememberSaveable { mutableIntStateOf(0) }

    Column(
        Modifier
            .padding(16.dp)
            .fillMaxWidth()
            .verticalScroll(rememberScrollState()),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        StageSwitch(stage) { stage = it }
        Spacer(Modifier.height(10.dp))
        if (stage == 0) CoarseStage(vm) else AlignStage(vm)
    }
}

/** Two-stage selector: coarse sensor alignment, then the polar scope. */
@Composable
private fun StageSwitch(stage: Int, onSelect: (Int) -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
        listOf("1 · Compass (sensors)", "2 · Polar align").forEachIndexed { i, label ->
            if (stage == i) {
                Button(onClick = { onSelect(i) }) { Text(label, maxLines = 1) }
            } else {
                OutlinedButton(onClick = { onSelect(i) }) { Text(label, maxLines = 1) }
            }
        }
    }
}

/** Stage 1: the live compass rose and turn/tilt guidance. */
@Composable
private fun CoarseStage(vm: CompassViewModel) {
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
        // Honest error bar. The uncertainty is the magnetometer's, and it is
        // whole degrees — never imply the sub-degree precision that competing
        // "sensor fusion" apps advertise, which no phone compass can deliver.
        Text(
            "declination %+.1f° applied • ".format(vm.declination) +
                accuracyClaim(vm.sensorAccuracy),
            style = MaterialTheme.typography.bodySmall,
            color = calibrationColor(vm.sensorAccuracy),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            "good enough to put the pole in the polar scope — use stage 2 for " +
                "arcminute accuracy, or drift/plate-solve to do better",
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
    }
}

/**
 * What the compass is actually worth right now. A phone magnetometer gives
 * 1-2 deg at best after a good calibration, and an uncalibrated one is not
 * trustworthy at any stated figure — so say that instead of printing a
 * confident number.
 */
private fun accuracyClaim(accuracy: Int): String = when (accuracy) {
    SensorManager.SENSOR_STATUS_ACCURACY_HIGH -> "heading good to roughly ±1-2°"
    SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM -> "heading good to roughly ±2-5°"
    SensorManager.SENSOR_STATUS_ACCURACY_LOW -> "heading uncertain, ±5° or worse"
    else -> "heading NOT trustworthy until calibrated"
}

/**
 * Stage 2: the twilight rough-align assistant.
 *
 * The phone is fixed to the mount; this reads its live attitude and gives
 * azimuth/altitude corrections that drive the mount's polar axis onto the
 * pole — usable BEFORE Polaris is visible, which is the whole point. Get the
 * error inside a polar-scope field here, then hand off to N.I.N.A. TPPA once
 * Polaris shows. The pole altitude comes from the Python core (refraction
 * included); the live pointing and the deltas are sensor-side.
 */
@Composable
private fun AlignStage(vm: CompassViewModel) {
    LaunchedEffect(vm.latitude, vm.longitude) {
        if (vm.latitude != null && vm.longitude != null && !vm.refractionReady) {
            vm.fetchRefractedAltitude()
        }
    }

    if (!vm.hasFix) {
        Text(
            "waiting for a GPS fix — the pole altitude equals your latitude, so a " +
                "position is needed. Open the Horizon or Plan tab once to acquire a " +
                "fix, then return.",
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
        return
    }

    MountSwitch(vm)
    Spacer(Modifier.height(8.dp))
    Text(
        calibrationHint(vm.sensorAccuracy),
        style = MaterialTheme.typography.bodySmall,
        color = calibrationColor(vm.sensorAccuracy),
        textAlign = TextAlign.Center,
    )
    Spacer(Modifier.height(8.dp))

    val c = vm.correction
    if (c == null) {
        Text("forming correction…", style = MaterialTheme.typography.bodyMedium)
        return
    }

    Bullseye(c, Modifier.fillMaxWidth().aspectRatio(1f))
    Spacer(Modifier.height(10.dp))
    BoltGuidance(c)
    Spacer(Modifier.height(10.dp))
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
        Readout("azimuth Δ", "%+.2f°".format(c.dAz))
        Readout("altitude Δ", "%+.2f°".format(c.dAlt))
        Readout("pole alt", "%.2f°".format(vm.targetAltitude))
    }
    Spacer(Modifier.height(8.dp))
    Text(
        "target altitude %.2f°%s. ".format(
            vm.targetAltitude,
            if (vm.refractionReady) {
                " (%+.1f' refraction)".format((vm.targetAltitude - vm.poleAltitude) * 60f)
            } else {
                ""
            },
        ) + accuracyClaim(vm.sensorAccuracy) +
            " — inside the inner ring Polaris will be in the polar scope when it " +
            "rises; refine with N.I.N.A. TPPA once it is visible.",
        style = MaterialTheme.typography.bodySmall,
        color = calibrationColor(vm.sensorAccuracy),
        textAlign = TextAlign.Center,
    )
    if (vm.alignError.isNotEmpty()) {
        Spacer(Modifier.height(6.dp))
        Text(
            "using your latitude for the pole altitude (core: ${vm.alignError})",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
            textAlign = TextAlign.Center,
        )
    }
}

/** How the phone is fixed to the mount — a sensor-frame choice, not a calibration. */
@Composable
private fun MountSwitch(vm: CompassViewModel) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            listOf(true to "Flat on tube", false to "Back camera").forEach { (flat, label) ->
                if (vm.flatMount == flat) {
                    Button(onClick = { vm.chooseFlatMount(flat) }) { Text(label, maxLines = 1) }
                } else {
                    OutlinedButton(onClick = { vm.chooseFlatMount(flat) }) { Text(label, maxLines = 1) }
                }
            }
        }
        Text(
            if (vm.flatMount) {
                "phone lying on the tube, its long edge along the polar axis"
            } else {
                "phone clamped so the back camera looks down the polar axis"
            },
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
    }
}

/**
 * Bullseye: centre is the pole, the dot is where the polar axis points now.
 * Drive the dot to the centre.
 *
 * Deliberately NOT a polar clock showing Polaris at its hour angle — in
 * twilight Polaris is not visible, so its true sky position tells the operator
 * nothing actionable. What matters is the error vector, drawn in the same
 * sense as the bolts move: right/left is azimuth, up/down is altitude.
 *
 * The rings are the two thresholds that actually matter: the inner ring is a
 * typical polar-scope field (so "inside it" means Polaris will appear in the
 * eyepiece), the outer rim is twice that, beyond which the dot is clamped.
 */
@Composable
private fun Bullseye(c: Correction, modifier: Modifier) {
    val onSurface = MaterialTheme.colorScheme.onSurface
    val accent = MaterialTheme.colorScheme.primary
    val labelPaint = remember(onSurface) {
        Paint().apply {
            color = onSurface.toArgb()
            textSize = 30f
            textAlign = Paint.Align.CENTER
            isAntiAlias = true
        }
    }

    Canvas(modifier) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val r = min(cx, cy) * 0.86f
        // Full-scale radius in degrees; the dot is clamped to the rim beyond it.
        val fullScaleDeg = SCOPE_FIELD_DEG * 2f
        val pxPerDeg = r / fullScaleDeg

        // rings: polar-scope field (inner) and twice it (outer rim)
        drawCircle(onSurface.copy(alpha = 0.30f), r, Offset(cx, cy), style = Stroke(2f))
        drawCircle(
            accent.copy(alpha = 0.55f), SCOPE_FIELD_DEG * pxPerDeg, Offset(cx, cy),
            style = Stroke(3f),
        )

        // cross-hairs
        drawLine(onSurface.copy(alpha = 0.25f), Offset(cx - r, cy), Offset(cx + r, cy), 2f)
        drawLine(onSurface.copy(alpha = 0.25f), Offset(cx, cy - r), Offset(cx, cy + r), 2f)

        // ring label
        drawContext.canvas.nativeCanvas.drawText(
            "%.0f°".format(SCOPE_FIELD_DEG),
            cx + SCOPE_FIELD_DEG * pxPerDeg + 26f, cy - 8f, labelPaint,
        )

        // The dot sits where the POLE is relative to the axis: a pole to the
        // right (+dAz) draws right, a pole higher (+dAlt) draws up (screen -y).
        // Driving the dot to the centre is exactly driving the deltas to zero.
        val hyp = hypot(c.dAz, c.dAlt)
        val scale = if (hyp > fullScaleDeg) fullScaleDeg / hyp else 1f
        val p = Offset(cx + c.dAz * scale * pxPerDeg, cy - c.dAlt * scale * pxPerDeg)

        drawLine(accent.copy(alpha = 0.45f), Offset(cx, cy), p, 3f)
        drawCircle(accent, 20f, p)
        // centre pip last so it stays visible under the dot when aligned
        drawCircle(onSurface, 6f, Offset(cx, cy))
    }
}

/** A typical polar-scope field of view, degrees — the "close enough" threshold. */
private const val SCOPE_FIELD_DEG = 5f

/**
 * The two bolt corrections, plain-language and monospaced so the numbers do
 * not jitter in width as they change.
 */
@Composable
private fun BoltGuidance(c: Correction) {
    val az = if (abs(c.dAz) < Correction.POLE_TOLERANCE_DEG) "azimuth aligned" else {
        "azimuth: turn %.1f° %s".format(abs(c.dAz), if (c.dAz > 0) "right (E)" else "left (W)")
    }
    val alt = if (abs(c.dAlt) < Correction.POLE_TOLERANCE_DEG) "altitude aligned" else {
        "altitude: %s %.1f°".format(if (c.dAlt > 0) "raise" else "lower", abs(c.dAlt))
    }
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            if (c.onTarget) "▲ axis on the pole" else az,
            style = MaterialTheme.typography.titleLarge,
            color = if (c.onTarget) MaterialTheme.colorScheme.primary
            else MaterialTheme.colorScheme.onSurface,
            fontFamily = FontFamily.Monospace,
            textAlign = TextAlign.Center,
        )
        if (!c.onTarget) {
            Text(
                alt,
                style = MaterialTheme.typography.titleLarge,
                fontFamily = FontFamily.Monospace,
                textAlign = TextAlign.Center,
            )
        }
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
