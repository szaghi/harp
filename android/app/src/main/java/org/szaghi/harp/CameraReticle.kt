package org.szaghi.harp

import android.graphics.Bitmap
import android.graphics.Paint
import android.hardware.camera2.CameraCharacteristics
import android.util.Size
import androidx.annotation.OptIn
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.UseCase
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import java.util.concurrent.Executors
import kotlin.math.atan
import kotlin.math.roundToInt

/**
 * Camera aiming surface for the horizon wizard: live rear-camera preview
 * (or a high-contrast false-color rendering of it) under an AR graticule.
 *
 * The graticule maps degrees to pixels linearly from the lens's true field
 * of view (camera2 characteristics; pinhole small-angle approximation) and
 * is rotated by the device roll so the drawn horizon stays horizontal in
 * the world. Tap anywhere to capture the CENTER-crosshair direction — the
 * capture uses the sensor pointing, not the tap position.
 */
@Composable
fun CameraReticle(
    vm: HorizonViewModel,
    falseColor: Boolean,
    modifier: Modifier = Modifier,
    onTap: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    // sensor long axis maps to the SCREEN VERTICAL in portrait
    var fovLong by remember { mutableFloatStateOf(66f) }
    var fovShort by remember { mutableFloatStateOf(50f) }
    var frame by remember { mutableStateOf<ImageBitmap?>(null) }
    var frameRotation by remember { mutableIntStateOf(90) }
    val previewView = remember { PreviewView(context) }

    DisposableEffect(falseColor) {
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        val executor = Executors.newSingleThreadExecutor()
        future.addListener({
            provider = future.get().also { p ->
                p.unbindAll()
                val useCases = mutableListOf<UseCase>()
                if (falseColor) {
                    @Suppress("DEPRECATION")
                    val analysis = ImageAnalysis.Builder()
                        .setTargetResolution(Size(320, 240))
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()
                    analysis.setAnalyzer(executor) { img ->
                        val bmp = falseColorBitmap(img)
                        frameRotation = img.imageInfo.rotationDegrees
                        img.close()
                        frame = bmp.asImageBitmap()
                    }
                    useCases += analysis
                } else {
                    useCases += Preview.Builder().build()
                        .also { it.surfaceProvider = previewView.surfaceProvider }
                }
                val camera = p.bindToLifecycle(
                    lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA,
                    *useCases.toTypedArray(),
                )
                readFov(camera.cameraInfo)?.let { (long, short) ->
                    fovLong = long
                    fovShort = short
                }
            }
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            provider?.unbindAll()
            executor.shutdown()
        }
    }

    Box(modifier.clickable { onTap() }) {
        if (falseColor) {
            frame?.let {
                Image(
                    it, null,
                    Modifier.fillMaxSize().rotate(frameRotation.toFloat()),
                    contentScale = ContentScale.Crop,
                )
            }
        } else {
            AndroidView({ previewView }, Modifier.fillMaxSize())
        }
        ReticleOverlay(vm, fovLong, fovShort, Modifier.fillMaxSize())
    }
}

@OptIn(ExperimentalCamera2Interop::class)
private fun readFov(info: androidx.camera.core.CameraInfo): Pair<Float, Float>? = try {
    val c2 = Camera2CameraInfo.from(info)
    val focal = c2.getCameraCharacteristic(
        CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS
    )?.firstOrNull()
    val sensor = c2.getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
    if (focal != null && sensor != null) {
        val long = Math.toDegrees(2.0 * atan(sensor.width / (2.0 * focal))).toFloat()
        val short = Math.toDegrees(2.0 * atan(sensor.height / (2.0 * focal))).toFloat()
        long to short
    } else null
} catch (_: Exception) {
    null
}

/** Az/alt graticule: 5-deg lines, thick red horizon, roll-compensated. */
@Composable
private fun ReticleOverlay(
    vm: HorizonViewModel,
    fovLong: Float,
    fovShort: Float,
    modifier: Modifier = Modifier,
) {
    val labelPaint = remember {
        Paint().apply {
            color = android.graphics.Color.YELLOW
            textSize = 32f
            setShadowLayer(4f, 0f, 0f, android.graphics.Color.BLACK)
        }
    }
    Canvas(modifier) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        // portrait: sensor long axis is vertical on screen
        val pxPerDegY = size.height / fovLong
        val pxPerDegX = size.width / fovShort

        fun outlined(start: Offset, end: Offset, color: Color, width: Float) {
            drawLine(Color.Black, start, end, width + 3f)
            drawLine(color, start, end, width)
        }

        // roll compensation keeps the drawn horizon horizontal in the world;
        // sign to be validated on device (flip here if the grid counter-rotates)
        rotate(-vm.roll, pivot = Offset(cx, cy)) {
            // altitude lines every 5 deg
            val altBase = (vm.altitude / 5f).roundToInt() * 5
            for (k in -4..4) {
                val altLine = altBase + k * 5
                if (altLine < -90 || altLine > 90) continue
                val y = cy - (altLine - vm.altitude) * pxPerDegY
                val isHorizon = altLine == 0
                outlined(
                    Offset(0f, y), Offset(size.width, y),
                    if (isHorizon) Color.Red else Color.Yellow,
                    if (isHorizon) 4f else 1.5f,
                )
                drawContext.canvas.nativeCanvas.drawText("${altLine}°", 8f, y - 6f, labelPaint)
            }
            // azimuth lines every 5 deg
            val azBase = (vm.azimuthTrue / 5f).roundToInt() * 5
            for (k in -3..3) {
                val azLine = azBase + k * 5
                var dAz = azLine - vm.azimuthTrue
                if (dAz > 180) dAz -= 360
                if (dAz < -180) dAz += 360
                val x = cx + dAz * pxPerDegX
                outlined(Offset(x, 0f), Offset(x, size.height), Color.Yellow, 1.5f)
                val azLabel = ((azLine % 360) + 360) % 360
                drawContext.canvas.nativeCanvas.drawText("${azLabel}°", x + 6f, 40f, labelPaint)
            }
        }
        // center crosshair: this is what a tap captures
        outlined(Offset(cx - 40f, cy), Offset(cx + 40f, cy), Color.Red, 3f)
        outlined(Offset(cx, cy - 40f), Offset(cx, cy + 40f), Color.Red, 3f)
    }
}

// high-contrast false color: luminance -> contrast stretch -> thermal LUT
private val LUT = IntArray(256) { v ->
    val t = (((v - 40) * 255) / 175).coerceIn(0, 255) // stretch 40..215 -> 0..255
    val r = (3 * t - 255).coerceIn(0, 255)
    val g = when {
        t < 128 -> 2 * t
        else -> 255 - 2 * (t - 128)
    }.coerceIn(0, 255)
    val b = (255 - 2 * t).coerceIn(0, 255)
    (0xFF shl 24) or (r shl 16) or (g shl 8) or b
}

private fun falseColorBitmap(img: ImageProxy): Bitmap {
    val plane = img.planes[0] // Y (luminance)
    val w = img.width
    val h = img.height
    val stride = plane.rowStride
    val buf = plane.buffer
    val pixels = IntArray(w * h)
    for (row in 0 until h) {
        val base = row * stride
        for (col in 0 until w) {
            pixels[row * w + col] = LUT[buf.get(base + col).toInt() and 0xFF]
        }
    }
    return Bitmap.createBitmap(pixels, w, h, Bitmap.Config.ARGB_8888)
}
