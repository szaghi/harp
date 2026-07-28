package org.szaghi.harp

import android.content.ContentValues
import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.util.Log
import androidx.annotation.OptIn
import androidx.camera.camera2.interop.Camera2CameraControl
import androidx.camera.camera2.interop.Camera2Interop
import androidx.camera.camera2.interop.CaptureRequestOptions
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.concurrent.futures.await
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.resume

private const val TAG = "HarpCapture"

/**
 * One frame's worth of manual camera settings.
 *
 * Everything here is an explicit instruction to the sensor: the point of the
 * Shoot tab is that nothing is decided automatically. [exposureNs] and [iso] are
 * only honoured when the device reports manual sensor support -- see
 * [CameraCapabilities.manualSensorSupported].
 *
 * @property focusDioptres 0.0 is infinity, which is where stars live
 * @property dng ask for RAW; silently unavailable on devices without it
 */
data class CaptureSettings(
    val exposureNs: Long,
    val iso: Int,
    val focusDioptres: Float = 0f,
    val dng: Boolean = true,
)

/**
 * What actually came back from a capture.
 *
 * [achievedExposureNs] is the load-bearing field. The sensor reports what it
 * really did, which is not always what was asked for: a sequence that believes
 * it is shooting 17 s subs while the driver quietly truncates to 8.3 s is the
 * exact failure this type exists to make visible.
 */
data class CaptureOutcome(
    val uri: Uri?,
    val requestedExposureNs: Long,
    val achievedExposureNs: Long,
    val achievedIso: Int,
    val error: String? = null,
) {
    val ok: Boolean get() = error == null && uri != null

    /**
     * False when the sensor silently gave a different exposure than requested.
     *
     * A zero [achievedExposureNs] means the device never reported one, which is
     * permitted on some hardware; that is treated as "no evidence of a problem"
     * rather than as a failure, because refusing to shoot on a device that
     * simply does not report metadata would be worse than the risk.
     */
    val exposureHonoured: Boolean
        get() = achievedExposureNs <= 0L ||
            exposureWithinTolerance(requestedExposureNs, achievedExposureNs)
}

/**
 * Binds the camera for the Shoot tab and drives manual, verified captures.
 *
 * CameraX handles lifecycle and use-case management; `Camera2Interop` supplies
 * the manual sensor controls CameraX does not surface directly (exposure time,
 * sensitivity, focus distance, stabilisation). One [ProcessCameraProvider] is
 * shared with the rest of the app -- a second, parallel raw Camera2 session
 * would fight this one for the device and break whichever tab bound second.
 */
class CaptureController(private val context: Context) {

    private var provider: ProcessCameraProvider? = null
    private var camera: Camera? = null
    private var imageCapture: ImageCapture? = null

    // Written by the session capture callback on a camera thread, read from the
    // capture coroutine: atomics rather than plain fields for visibility.
    private val lastExposureNs = AtomicLong(0L)
    private val lastIso = AtomicInteger(0)

    // Set by captureFrame() before it triggers a still, completed by the
    // capture callback with that frame's own (exposure, ISO). Correlating this
    // way -- rather than reading the atomics after onImageSaved -- removes the
    // ordering assumption between the two independent callbacks.
    private val pendingMetadata =
        AtomicReference<CompletableDeferred<Pair<Long, Int>>?>(null)

    /** Interrogated once per bind; drives which controls the UI enables. */
    var capabilities: CameraCapabilities? = null
        private set

    /**
     * The most recent exposure the sensor reported, nanoseconds.
     *
     * This is the verification half of the extended-exposure approach in
     * [ExposureCalibration]: without reading back what the sensor actually did,
     * requesting more than the advertised maximum would be the blind
     * over-requesting that makes the technique unsafe.
     */
    val achievedExposureNs: Long get() = lastExposureNs.get()

    /** The most recent ISO the sensor reported. */
    val achievedIso: Int get() = lastIso.get()

    /**
     * Bind preview, analysis and capture to [owner]; returns the probed caps.
     *
     * The preview is deliberately left on auto-exposure. A preview at true
     * capture settings is unusably black, and the viewfinder has its own
     * (typically ~1 s) exposure ceiling regardless of what the still capture can
     * reach -- so framing uses gain, not shutter (see the preview-gain note in
     * ShootScreen).
     */
    @OptIn(ExperimentalCamera2Interop::class)
    suspend fun bind(
        owner: LifecycleOwner,
        surfaceProvider: Preview.SurfaceProvider,
        analyzerExecutor: Executor,
        analyzer: ImageAnalysis.Analyzer,
        wantDng: Boolean,
    ): CameraCapabilities {
        val p = ProcessCameraProvider.getInstance(context).await()
        // The caller may have been disposed while the provider future was in
        // flight; binding now would attach the camera to a dead lifecycle.
        currentCoroutineContext().ensureActive()
        provider = p
        p.unbindAll()

        val preview = Preview.Builder().build().also { it.surfaceProvider = surfaceProvider }

        val analysis = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()
            .also { it.setAnalyzer(analyzerExecutor, analyzer) }

        // Probe before choosing an output format: requesting RAW on a device
        // that cannot produce it fails at bind time.
        val selector = CameraSelector.DEFAULT_BACK_CAMERA
        val caps = CameraCapabilities.probe(p.getCameraInfo(selector))
        capabilities = caps

        val captureBuilder = ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
        if (wantDng && caps.dngSupported) {
            captureBuilder.setOutputFormat(ImageCapture.OUTPUT_FORMAT_RAW)
        }

        // The session capture callback is how achieved exposure/ISO get back to
        // us; CameraX has no first-class API for it.
        //
        // CRITICAL: this callback fires for EVERY request in the session, which
        // includes the preview's repeating auto-exposure frames -- and the
        // preview deliberately runs on auto. Without the capture-intent filter
        // below, a preview frame lands between the still capture and the read
        // and overwrites the metadata, so the verification would be reporting
        // the viewfinder's exposure instead of the frame we just saved. That
        // would silently defeat the guard the whole extended-exposure approach
        // depends on.
        Camera2Interop.Extender(captureBuilder).setSessionCaptureCallback(
            object : CameraCaptureSession.CaptureCallback() {
                override fun onCaptureCompleted(
                    session: CameraCaptureSession,
                    request: CaptureRequest,
                    result: TotalCaptureResult,
                ) {
                    val intent = request.get(CaptureRequest.CONTROL_CAPTURE_INTENT)
                    if (intent != CameraMetadata.CONTROL_CAPTURE_INTENT_STILL_CAPTURE) return

                    val exp = result.get(CaptureResult.SENSOR_EXPOSURE_TIME) ?: 0L
                    val sens = result.get(CaptureResult.SENSOR_SENSITIVITY) ?: 0
                    lastExposureNs.set(exp)
                    lastIso.set(sens)
                    // Hand this frame's own metadata to whichever captureFrame()
                    // is waiting, rather than letting it read a stale atomic.
                    pendingMetadata.getAndSet(null)?.complete(exp to sens)
                }
            },
        )

        val capture = captureBuilder.build()
        imageCapture = capture

        camera = p.bindToLifecycle(owner, selector, preview, analysis, capture)
        return caps
    }

    fun unbind() {
        provider?.unbindAll()
        provider = null
        camera = null
        imageCapture = null
    }

    /**
     * Push manual settings to the sensor.
     *
     * Every request carries AE, AWB and stabilisation OFF. Omitting AE-off is
     * the classic manual-camera bug -- the auto-exposure routine silently
     * overrides the values just set. Omitting stabilisation-off is the
     * astro-specific one: on a tripod OIS has no real motion to correct, and its
     * drift smears stars across a long exposure.
     */
    @OptIn(ExperimentalCamera2Interop::class)
    suspend fun applySettings(s: CaptureSettings, caps: CameraCapabilities) {
        val cam = camera ?: return
        val builder = CaptureRequestOptions.Builder()
            .setCaptureRequestOption(
                CaptureRequest.CONTROL_AE_MODE,
                CameraMetadata.CONTROL_AE_MODE_OFF,
            )
            .setCaptureRequestOption(
                CaptureRequest.CONTROL_AWB_MODE,
                CameraMetadata.CONTROL_AWB_MODE_OFF,
            )

        if (caps.manualSensorSupported) {
            builder.setCaptureRequestOption(CaptureRequest.SENSOR_EXPOSURE_TIME, s.exposureNs)
            builder.setCaptureRequestOption(CaptureRequest.SENSOR_SENSITIVITY, s.iso)
            // Without an explicit frame duration the sensor may hold a frame
            // rate that cannot accommodate the exposure, and truncate it.
            builder.setCaptureRequestOption(CaptureRequest.SENSOR_FRAME_DURATION, s.exposureNs)
        }

        if (caps.oisSupported) {
            builder.setCaptureRequestOption(
                CaptureRequest.LENS_OPTICAL_STABILIZATION_MODE,
                CameraMetadata.LENS_OPTICAL_STABILIZATION_MODE_OFF,
            )
        }
        builder.setCaptureRequestOption(
            CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE,
            CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_OFF,
        )

        if (caps.manualFocusSupported) {
            builder.setCaptureRequestOption(
                CaptureRequest.CONTROL_AF_MODE,
                CameraMetadata.CONTROL_AF_MODE_OFF,
            )
            builder.setCaptureRequestOption(CaptureRequest.LENS_FOCUS_DISTANCE, s.focusDioptres)
        }

        Camera2CameraControl.from(cam.cameraControl)
            .setCaptureRequestOptions(builder.build())
            .await()
    }

    /**
     * Capture one frame into [relativeDir] and report what the sensor did.
     *
     * Never throws: a failed frame in an unattended sequence must be logged and
     * surfaced, not allowed to tear the run down.
     */
    suspend fun captureFrame(
        relativeDir: String,
        fileName: String,
        settings: CaptureSettings,
        dng: Boolean,
    ): CaptureOutcome {
        val capture = imageCapture
            ?: return CaptureOutcome(null, settings.exposureNs, 0L, 0, "camera not bound")

        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
            put(
                MediaStore.MediaColumns.MIME_TYPE,
                if (dng) "image/x-adobe-dng" else "image/jpeg",
            )
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.MediaColumns.RELATIVE_PATH, relativeDir)
            }
        }
        val options = ImageCapture.OutputFileOptions.Builder(
            context.contentResolver,
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            values,
        ).build()

        // Arm the correlation slot before triggering, so the still's own
        // metadata cannot be missed or confused with a neighbouring frame's.
        val metadata = CompletableDeferred<Pair<Long, Int>>()
        pendingMetadata.set(metadata)

        val saved = suspendCancellableCoroutine { cont ->
            capture.takePicture(
                options,
                directExecutor,
                object : ImageCapture.OnImageSavedCallback {
                    override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                        cont.resume(Result.success(output.savedUri))
                    }

                    override fun onError(exc: ImageCaptureException) {
                        Log.w(TAG, "capture failed: ${exc.message}", exc)
                        cont.resume(Result.failure(exc))
                    }
                },
            )
        }

        // Wait briefly for this frame's metadata. Not all devices report it; a
        // timeout yields zeros, which CaptureOutcome.exposureHonoured treats as
        // "no evidence of a problem" rather than as a failure -- refusing to
        // shoot on a device that simply stays quiet would be worse than the risk.
        val (exp, isoAchieved) = withTimeoutOrNull(METADATA_TIMEOUT_MS) { metadata.await() }
            ?: (0L to 0)
        pendingMetadata.compareAndSet(metadata, null)

        return CaptureOutcome(
            uri = saved.getOrNull(),
            requestedExposureNs = settings.exposureNs,
            achievedExposureNs = exp,
            achievedIso = isoAchieved,
            error = saved.exceptionOrNull()?.message,
        )
    }

    private companion object {
        /** Runs the callback on whichever thread completes it; nothing here blocks. */
        val directExecutor = Executor { it.run() }

        /**
         * How long to wait for a frame's capture metadata after it is saved.
         *
         * Generous: the metadata callback normally precedes image delivery, so
         * this only bites on devices that never report it at all.
         */
        const val METADATA_TIMEOUT_MS = 2_000L
    }
}

/**
 * Write a small text file beside the captured frames, via MediaStore.
 *
 * Used for `session.json`, the manifest that makes a captured folder
 * self-documenting. Goes through MediaStore rather than a direct path so the
 * sequence directory stays one coherent unit that survives uninstall.
 */
fun writeTextToMediaStore(
    context: Context,
    relativeDir: String,
    fileName: String,
    text: String,
) {
    val values = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
        put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            put(MediaStore.MediaColumns.RELATIVE_PATH, relativeDir)
        }
    }
    // MediaStore.Files, NOT Downloads: RELATIVE_PATH is honoured within the
    // collection it is inserted into, not across collections, so a DCIM/ path
    // in Downloads lands in a separate Downloads/DCIM/ tree rather than beside
    // the frames it documents. Files shares the frames' path domain and keeps
    // the JSON out of gallery apps.
    val collection = MediaStore.Files.getContentUri("external")
    val uri = context.contentResolver.insert(collection, values) ?: return
    context.contentResolver.openOutputStream(uri)?.use { it.write(text.toByteArray()) }
}
