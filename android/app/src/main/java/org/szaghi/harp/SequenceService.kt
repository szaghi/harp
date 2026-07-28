package org.szaghi.harp

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

private const val TAG = "HarpSequence"
private const val CHANNEL_ID = "harp_sequence"
private const val NOTIFICATION_ID = 4201

/** Live progress of the running sequence, observed by the UI. */
data class SequenceProgress(
    val running: Boolean = false,
    val frame: Int = 0,
    val total: Int = 0,
    val etaMs: Long = 0L,
    val issues: List<SequenceIssue> = emptyList(),
    val finished: Boolean = false,
) {
    val fraction: Float get() = if (total <= 0) 0f else frame.toFloat() / total
}

/**
 * Runs a capture sequence as a foreground service.
 *
 * A one-to-two hour run cannot live in a ViewModel coroutine: Doze suspends it
 * and the user finds sixty frames instead of four hundred at dawn. A foreground
 * service holding a wake lock is the only arrangement Android reliably honours,
 * and the persistent notification is a requirement rather than a courtesy.
 *
 * Frame timing is scheduled against a monotonic start instant, never by
 * accumulating per-frame sleeps -- accumulated error over hundreds of frames is
 * minutes of drift.
 */
class SequenceService : Service() {

    private val job = SupervisorJob()
    private val scope = CoroutineScope(job)
    private var wakeLock: PowerManager.WakeLock? = null
    private var runner: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSequence()
            return START_NOT_STICKY
        }

        val plan = intent?.let { planFrom(it) }
        if (plan == null) {
            stopSelf()
            return START_NOT_STICKY
        }

        createChannel()
        startForegroundCompat(notification(0, plan.frames, "starting"))
        acquireWakeLock(plan.totalMs)
        runner = scope.launch { run(plan) }
        // START_NOT_STICKY: a sequence killed by the system must not silently
        // restart hours later pointing at a sky that has moved.
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        releaseWakeLock()
        scope.cancel()
        super.onDestroy()
    }

    /**
     * The capture loop.
     *
     * Each frame waits until its scheduled offset from the start instant rather
     * than sleeping a fixed interval, so one slow write delays a single frame
     * instead of shifting every frame after it.
     */
    private suspend fun run(plan: SequencePlan) {
        val controller = controllerRef
        if (controller == null) {
            finish(listOf(SequenceIssue.CaptureFailed(0, "camera not bound")))
            return
        }
        val caps = controller.capabilities
        if (caps == null) {
            finish(listOf(SequenceIssue.CaptureFailed(0, "capabilities unknown")))
            return
        }

        val stamp = utcStamp()
        val dir = "DCIM/HARP/${plan.name}_$stamp"
        val results = mutableListOf<CaptureOutcome>()
        val issues = mutableListOf<SequenceIssue>()
        val startMs = SystemClock.elapsedRealtime()

        val settings = CaptureSettings(
            exposureNs = plan.exposureNs,
            iso = plan.iso,
            focusDioptres = plan.focusDioptres,
            dng = plan.dng,
        )
        runCatching { controller.applySettings(settings, caps) }

        for (i in 0 until plan.frames) {
            // This coroutine's own job, NOT scope.isActive: stopSequence()
            // cancels the child job launched in the scope, which leaves the
            // parent scope active. Checking the scope would make the Stop
            // button silently do nothing and hold the wake lock for the full
            // planned duration.
            if (!currentCoroutineContext().isActive) break

            // Monotonic scheduling: sleep until this frame's offset, not for a
            // fixed interval. elapsedRealtime keeps counting during Doze, so it
            // is the right clock even when the screen is off.
            val due = startMs + plan.frameOffsetMs(i)
            val wait = due - SystemClock.elapsedRealtime()
            if (wait > 0) delay(wait)

            _progress.value = SequenceProgress(
                running = true,
                frame = i + 1,
                total = plan.frames,
                etaMs = (plan.totalMs - (SystemClock.elapsedRealtime() - startMs))
                    .coerceAtLeast(0L),
                issues = issues.toList(),
            )
            notify(i + 1, plan.frames, "capturing")

            val ext = if (plan.dng) "dng" else "jpg"
            val name = String.format(Locale.US, "frame_%04d.%s", i + 1, ext)
            val out = controller.captureFrame(dir, name, settings, plan.dng)
            results += out

            if (!out.ok) {
                issues += SequenceIssue.CaptureFailed(i + 1, out.error ?: "unknown")
                // One bad frame is tolerable; a broken camera is not.
                if (issues.count { it is SequenceIssue.CaptureFailed } >= MAX_FRAME_FAILURES) {
                    break
                }
            } else if (!out.exposureHonoured) {
                // The verification guard. A truncated exposure means every
                // remaining frame is wrong too, so stop rather than fill the
                // card with subs that will not stack with one another.
                issues += SequenceIssue.ExposureDrift(
                    out.requestedExposureNs,
                    out.achievedExposureNs,
                )
                break
            }
        }

        writeSessionJson(dir, plan, stamp, results, issues)
        finish(issues)
    }

    private fun finish(issues: List<SequenceIssue>) {
        _progress.value = _progress.value.copy(
            running = false,
            finished = true,
            issues = issues,
        )
        // ShootScreen deliberately skips unbinding while a sequence runs, so if
        // the tab was closed mid-run nothing else will release the camera. Once
        // the screen is gone the controller has no owner: drop it here.
        if (!uiVisible) {
            runCatching { controllerRef?.unbind() }
            controllerRef = null
        }
        releaseWakeLock()
        stopForegroundCompat()
        stopSelf()
    }

    private fun stopSequence() {
        runner?.cancel()
        finish(_progress.value.issues)
    }

    /**
     * Write the session manifest beside the frames.
     *
     * Makes the capture self-documenting: which settings produced these subs,
     * what the sensor actually delivered, and which frames failed. Without it a
     * folder of DNGs a week later is an unlabelled mystery.
     */
    private fun writeSessionJson(
        dir: String,
        plan: SequencePlan,
        stamp: String,
        results: List<CaptureOutcome>,
        issues: List<SequenceIssue>,
    ) {
        val json = buildString {
            append("{\n")
            append("  \"sequence\": \"").append(plan.name).append("\",\n")
            append("  \"startedUtc\": \"").append(stamp).append("\",\n")
            append("  \"exposureNs\": ").append(plan.exposureNs).append(",\n")
            append("  \"iso\": ").append(plan.iso).append(",\n")
            append("  \"focusDioptres\": ").append(plan.focusDioptres).append(",\n")
            append("  \"intervalMs\": ").append(plan.intervalMs).append(",\n")
            append("  \"framesPlanned\": ").append(plan.frames).append(",\n")
            append("  \"framesCaptured\": ").append(results.count { it.ok }).append(",\n")
            append("  \"dng\": ").append(plan.dng).append(",\n")
            append("  \"frames\": [\n")
            results.forEachIndexed { i, r ->
                append("    {\"index\": ").append(i + 1)
                append(", \"requestedNs\": ").append(r.requestedExposureNs)
                append(", \"achievedNs\": ").append(r.achievedExposureNs)
                append(", \"iso\": ").append(r.achievedIso)
                append(", \"ok\": ").append(r.ok)
                append('}')
                if (i < results.size - 1) append(',')
                append('\n')
            }
            append("  ],\n")
            append("  \"issues\": [")
            append(issues.joinToString(", ") { "\"${it.message.replace('"', '\'')}\"" })
            append("]\n}\n")
        }
        runCatching { writeTextToMediaStore(this, dir, "session.json", json) }
            .onFailure { Log.w(TAG, "session.json failed: ${it.message}") }
    }

    // --- notification / wake lock -------------------------------------------

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val mgr = getSystemService(NotificationManager::class.java)
        if (mgr.getNotificationChannel(CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Capture sequence",
                    // LOW: informative, and must never light the screen or make
                    // a sound in the middle of a dark-site session.
                    NotificationManager.IMPORTANCE_LOW,
                ),
            )
        }
    }

    private fun notification(frame: Int, total: Int, state: String): Notification {
        val stopIntent = PendingIntent.getService(
            this,
            0,
            Intent(this, SequenceService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("HARP capture: $state")
            .setContentText(if (total > 0) "Frame $frame of $total" else "starting")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .setProgress(total.coerceAtLeast(1), frame, false)
            // An explicit icon: a null one is tolerated but renders blank on
            // some OEM shades, and this is the control that stops a running
            // capture -- it needs to be unmistakable at 3 a.m.
            .addAction(
                Notification.Action.Builder(
                    Icon.createWithResource(this, android.R.drawable.ic_menu_close_clear_cancel),
                    "Stop",
                    stopIntent,
                ).build(),
            )
            .build()
    }

    private fun notify(frame: Int, total: Int, state: String) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, notification(frame, total, state))
    }

    private fun startForegroundCompat(n: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
        } else {
            startForeground(NOTIFICATION_ID, n)
        }
    }

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
    }

    private fun acquireWakeLock(durationMs: Long) {
        val pm = getSystemService(PowerManager::class.java)
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "harp:sequence").apply {
            setReferenceCounted(false)
            // Timeout as a backstop: a leaked wake lock flattens the battery,
            // which on a dark site is worse than a lost sequence.
            acquire(durationMs + WAKE_LOCK_SLACK_MS)
        }
    }

    private fun releaseWakeLock() {
        runCatching { wakeLock?.takeIf { it.isHeld }?.release() }
        wakeLock = null
    }

    companion object {
        const val ACTION_START = "org.szaghi.harp.SEQUENCE_START"
        const val ACTION_STOP = "org.szaghi.harp.SEQUENCE_STOP"
        const val MAX_FRAME_FAILURES = 3
        const val WAKE_LOCK_SLACK_MS = 60_000L

        private val _progress = MutableStateFlow(SequenceProgress())

        /** Observed by the Shoot tab; survives the screen being closed. */
        val progress: StateFlow<SequenceProgress> = _progress.asStateFlow()

        /**
         * The bound camera, shared with the Shoot tab.
         *
         * The service reuses the controller the UI already bound rather than
         * opening a second camera session -- two sessions fight for the device
         * and whichever binds second loses.
         */
        @Volatile
        var controllerRef: CaptureController? = null

        /**
         * True while the Shoot tab is on screen and owns the camera binding.
         *
         * Decides who releases the controller: the screen when it is present,
         * the service when the sequence outlives it. Without this, either the
         * camera is torn down mid-sequence or it is left bound forever.
         */
        @Volatile
        var uiVisible: Boolean = false

        fun start(context: Context, plan: SequencePlan) {
            val i = Intent(context, SequenceService::class.java)
                .setAction(ACTION_START)
                .putExtra("name", plan.name)
                .putExtra("exposureNs", plan.exposureNs)
                .putExtra("iso", plan.iso)
                .putExtra("focusDioptres", plan.focusDioptres)
                .putExtra("frames", plan.frames)
                .putExtra("intervalMs", plan.intervalMs)
                .putExtra("startDelayMs", plan.startDelayMs)
                .putExtra("ditherEvery", plan.ditherEvery)
                .putExtra("ditherPauseMs", plan.ditherPauseMs)
                .putExtra("dng", plan.dng)
            context.startForegroundService(i)
        }

        fun stop(context: Context) {
            context.startService(
                Intent(context, SequenceService::class.java).setAction(ACTION_STOP),
            )
        }

        private fun planFrom(intent: Intent): SequencePlan? {
            val name = intent.getStringExtra("name") ?: return null
            val frames = intent.getIntExtra("frames", 0)
            if (frames <= 0) return null
            return SequencePlan(
                name = name,
                exposureNs = intent.getLongExtra("exposureNs", 0L),
                iso = intent.getIntExtra("iso", 0),
                focusDioptres = intent.getFloatExtra("focusDioptres", 0f),
                frames = frames,
                intervalMs = intent.getLongExtra("intervalMs", 0L),
                startDelayMs = intent.getLongExtra("startDelayMs", 0L),
                ditherEvery = intent.getIntExtra("ditherEvery", 0),
                ditherPauseMs = intent.getLongExtra("ditherPauseMs", 0L),
                dng = intent.getBooleanExtra("dng", true),
            )
        }

        /** UTC, filename-safe: the directory stamp and the manifest date. */
        fun utcStamp(): String = SimpleDateFormat("yyyyMMdd'T'HHmmss'Z'", Locale.US)
            .apply { timeZone = TimeZone.getTimeZone("UTC") }
            .format(Date())
    }
}
