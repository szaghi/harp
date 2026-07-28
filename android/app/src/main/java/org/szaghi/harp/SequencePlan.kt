package org.szaghi.harp

import java.util.Locale

/**
 * Everything needed to run one unattended capture sequence.
 *
 * A sequence is bounded by design: at 8-17 s subs and 1-2 h of integration the
 * worst case is under a thousand frames in a single sitting, so there is no
 * chunking, no rolling deletion and no cross-session resume to reason about.
 * One sequence, one directory, one night.
 *
 * @property startDelayMs settle time before frame 1 -- kills shutter shake
 * @property intervalMs gap between frame *starts*, not between end and start
 * @property ditherEvery pause every N frames for a manual nudge; 0 disables
 */
data class SequencePlan(
    val name: String,
    val exposureNs: Long,
    val iso: Int,
    val focusDioptres: Float,
    val frames: Int,
    val intervalMs: Long,
    val startDelayMs: Long = 5_000L,
    val ditherEvery: Int = 0,
    val ditherPauseMs: Long = 0L,
    val dng: Boolean = true,
) {
    /** Wall-clock length including the start delay, milliseconds. */
    val totalMs: Long
        get() {
            val dithers = if (ditherEvery > 0) (frames - 1) / ditherEvery else 0
            return startDelayMs + frames.toLong() * intervalMs + dithers * ditherPauseMs
        }

    /** Total light collected -- what actually determines the result. */
    val integrationMs: Long get() = frames.toLong() * (exposureNs / 1_000_000L)

    /** Rough disc cost. DNG size is resolution-driven and stable per device. */
    fun estimatedBytes(perFrameBytes: Long = ESTIMATED_DNG_BYTES): Long =
        frames.toLong() * perFrameBytes

    /**
     * The soonest frame [index] may start, relative to sequence start.
     *
     * Computed from the index rather than accumulated: adding a sleep per frame
     * lets scheduling error compound, and over 400 frames that drift is minutes.
     */
    fun frameOffsetMs(index: Int): Long {
        val dithers = if (ditherEvery > 0) index / ditherEvery else 0
        return startDelayMs + index.toLong() * intervalMs + dithers * ditherPauseMs
    }

    companion object {
        /** A 12.5 MP DNG runs 12-25 MB; 20 is a safe planning figure. */
        const val ESTIMATED_DNG_BYTES = 20L * 1024 * 1024

        /**
         * Writing a full-resolution DNG is not instant, and the interval must
         * cover it or every frame starts late. If measurement on device shows
         * this is too small, the interval is I/O-bound rather than
         * exposure-bound -- which changes what the user should tune.
         */
        const val WRITE_ALLOWANCE_MS = 2_000L

        /** Shortest interval that can actually hold [exposureNs] plus the write. */
        fun minIntervalMs(exposureNs: Long): Long =
            exposureNs / 1_000_000L + WRITE_ALLOWANCE_MS

        /**
         * Frames that fit in [durationMs] -- the "enter either one" convenience.
         *
         * Duration is what users actually think in ("two hours on Andromeda"),
         * so the frame count derives from it rather than the other way round.
         */
        fun framesForDuration(durationMs: Long, intervalMs: Long): Int =
            if (intervalMs <= 0L) 0 else (durationMs / intervalMs).toInt().coerceAtLeast(1)

        /** "1 h 12 m" / "45 m 30 s" / "30 s", for the estimate line. */
        fun formatDuration(ms: Long): String {
            val totalSec = ms / 1000
            val h = totalSec / 3600
            val m = (totalSec % 3600) / 60
            val s = totalSec % 60
            return when {
                h > 0 -> String.format(Locale.US, "%d h %02d m", h, m)
                m > 0 -> String.format(Locale.US, "%d m %02d s", m, s)
                else -> String.format(Locale.US, "%d s", s)
            }
        }

        /** "8.5 GB" / "740 MB", for the storage warning. */
        fun formatBytes(b: Long): String {
            val gb = b / (1024.0 * 1024.0 * 1024.0)
            return if (gb >= 1.0) {
                String.format(Locale.US, "%.1f GB", gb)
            } else {
                String.format(Locale.US, "%.0f MB", b / (1024.0 * 1024.0))
            }
        }
    }
}

/**
 * A reason the sequence should not start, or should stop.
 *
 * Unattended capture is exactly where silent failure hurts most: the user is
 * asleep or looking at the sky, and a run that quietly does the wrong thing
 * wastes the whole night. Every one of these is surfaced, never swallowed.
 */
sealed interface SequenceIssue {
    val message: String

    /** Blocks the start: the frames would not fit on the device. */
    data class InsufficientStorage(val needBytes: Long, val freeBytes: Long) : SequenceIssue {
        override val message: String
            get() = "Needs ${SequencePlan.formatBytes(needBytes)} but only " +
                "${SequencePlan.formatBytes(freeBytes)} free"
    }

    /** Blocks the start: the interval cannot hold the exposure plus the write. */
    data class IntervalTooShort(val intervalMs: Long, val minMs: Long) : SequenceIssue {
        override val message: String
            get() = String.format(
                Locale.US,
                "Interval %.1fs is below the %.1fs needed for this exposure plus the write",
                intervalMs / 1000.0,
                minMs / 1000.0,
            )
    }

    /** Warns: the sequence probably outlasts the charge. */
    data class BatteryLow(val percent: Int) : SequenceIssue {
        override val message: String
            get() = "Battery at $percent% - a long sequence needs external power"
    }

    /** Warns, or pauses: a hot sensor means more dark current and more noise. */
    data class Thermal(val status: String) : SequenceIssue {
        override val message: String get() = "Device thermal status: $status"
    }

    /** Stops the run: the sensor is not delivering the requested exposure. */
    data class ExposureDrift(val requestedNs: Long, val achievedNs: Long) : SequenceIssue {
        override val message: String
            get() = "Sensor gave ${ShootViewModel.formatExposure(achievedNs)} instead of " +
                "${ShootViewModel.formatExposure(requestedNs)} - stopping"
    }

    /** Stops the run: frames are failing to save. */
    data class CaptureFailed(val index: Int, val reason: String) : SequenceIssue {
        override val message: String get() = "Frame $index failed: $reason"
    }
}

/** Below this, a multi-hour sequence is unlikely to finish on internal battery. */
const val BATTERY_WARN_PERCENT = 50

/**
 * Pre-flight checks, run before a single frame is taken.
 *
 * Storage is the one that genuinely bites: at ~20 MB a frame, a two-hour run is
 * several gigabytes, and discovering the shortfall at frame 300 means losing the
 * session.
 */
fun preflight(
    plan: SequencePlan,
    freeBytes: Long,
    batteryPercent: Int,
    thermalStatus: String?,
): List<SequenceIssue> = buildList {
    val minInterval = SequencePlan.minIntervalMs(plan.exposureNs)
    if (plan.intervalMs < minInterval) {
        add(SequenceIssue.IntervalTooShort(plan.intervalMs, minInterval))
    }
    val need = plan.estimatedBytes()
    if (need > freeBytes) add(SequenceIssue.InsufficientStorage(need, freeBytes))
    if (batteryPercent in 1..BATTERY_WARN_PERCENT) {
        add(SequenceIssue.BatteryLow(batteryPercent))
    }
    thermalStatus?.let { add(SequenceIssue.Thermal(it)) }
}

/** True when an issue must prevent the sequence from starting at all. */
fun SequenceIssue.isBlocking(): Boolean = when (this) {
    is SequenceIssue.InsufficientStorage, is SequenceIssue.IntervalTooShort -> true
    else -> false
}
