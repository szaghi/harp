package org.szaghi.harp

import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraMetadata
import androidx.annotation.OptIn
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.CameraInfo
import androidx.camera.core.ImageCapture
import java.util.Locale
import kotlin.math.abs
import kotlin.math.atan

/**
 * What the camera hardware actually supports, interrogated rather than assumed.
 *
 * Manual sensor control is not universal on Android: only `FULL` and `LEVEL_3`
 * devices guarantee that a requested `SENSOR_EXPOSURE_TIME` is honoured, and
 * `LIMITED`/`LEGACY` devices may silently ignore it. Every control in the Shoot
 * tab is gated on the values here, and unsupported ones are disabled with a
 * stated reason rather than hidden.
 *
 * Units are Camera2's: exposure in nanoseconds, sensitivity in ISO.
 * [maxAnalogIso] matters more in practice than [isoMax] -- see its docs.
 */
data class CameraCapabilities(
    /** `LEGACY`, `LIMITED`, `FULL`, `LEVEL_3`, `EXTERNAL`, or `UNKNOWN`. */
    val hardwareLevel: String,
    /** True when the device guarantees manual sensor control. */
    val manualSensorSupported: Boolean,
    /** Shortest exposure the sensor advertises, nanoseconds. */
    val exposureMinNs: Long,
    /**
     * Longest exposure the sensor *advertises*, nanoseconds.
     *
     * A conservative advertisement, not always an enforcement boundary: some
     * drivers honour longer requests (see [ExposureCalibration]). Treat this as
     * the safe default and anything beyond it as opt-in and measured.
     */
    val exposureMaxNs: Long,
    val isoMin: Int,
    val isoMax: Int,
    /**
     * Highest ISO reached by *analog* gain, or null if unreported.
     *
     * Above this the sensor multiplies after the ADC: digital gain amplifies
     * noise and signal alike and costs highlight headroom, achieving nothing a
     * later stretch could not. The UI marks it as the practical ceiling.
     */
    val maxAnalogIso: Int?,
    /** True when the camera can emit `RAW_SENSOR` buffers (a DNG prerequisite). */
    val rawCapable: Boolean,
    /** True when CameraX will actually hand us DNG for this camera. */
    val dngSupported: Boolean,
    /** True when `LENS_FOCUS_DISTANCE` is settable (i.e. not a fixed-focus lens). */
    val manualFocusSupported: Boolean,
    /** Dioptres at the near focus limit; 0.0 is infinity. Null if unreported. */
    val minFocusDistanceDioptres: Float?,
    /** True when optical stabilisation exists -- and so must be turned off. */
    val oisSupported: Boolean,
    /**
     * Effective focal length in mm, or null when unreported.
     *
     * Optics rather than framing: this and the two below feed the exposure
     * advisor, which needs what the lens gathers and how finely the sensor
     * samples it. [readFov] reads the same characteristics for the reticle's
     * graticule but keeps only the resulting angles, so the raw values are
     * carried here instead of being probed twice.
     */
    val focalLengthMm: Float? = null,
    /** Focal ratio, or null when unreported. Drives light per unit area. */
    val fNumber: Float? = null,
    /**
     * Physical pixel size in micrometres, or null when underivable.
     *
     * Finer pixels show trailing sooner, which is why the NPF rule beats the
     * older "500 rule" at phone pixel scales.
     */
    val pixelPitchUm: Float? = null,
) {
    /** True when the advisor has every optical input it needs. */
    val opticsKnown: Boolean
        get() = focalLengthMm != null && fNumber != null && pixelPitchUm != null

    /** Advertised maximum exposure in seconds, for display. */
    val exposureMaxSec: Double get() = exposureMaxNs / NANOS_PER_SECOND

    /**
     * A blunt one-line verdict for the capability card.
     *
     * The user should learn at the kitchen table that the phone cannot do this,
     * not at 2 a.m. on a dark site.
     */
    fun summary(): String = buildString {
        append(hardwareLevel)
        append(" - max ")
        // Locale.US, not the default: on an it_IT/de_DE device the default
        // renders "8,3" where the rest of the UI reads these as decimal points.
        append(String.format(Locale.US, "%.1f", exposureMaxSec))
        append(" s, ISO ")
        append(isoMin).append('-').append(isoMax)
        maxAnalogIso?.let { append(" (analog to ").append(it).append(')') }
        append(if (dngSupported) ", DNG" else ", no DNG")
        if (!manualSensorSupported) append(" - MANUAL CONTROL NOT GUARANTEED")
    }

    companion object {
        const val LEVEL_UNKNOWN = "UNKNOWN"
        const val NANOS_PER_SECOND = 1_000_000_000.0

        /**
         * Interrogate [info] for everything the Shoot tab needs.
         *
         * Never throws: an unreadable characteristic degrades to a conservative
         * value, because a camera tab that crashes on an unexpected device is
         * worse than one reporting reduced capability.
         */
        @OptIn(ExperimentalCamera2Interop::class)
        fun probe(info: CameraInfo): CameraCapabilities {
            val c2 = Camera2CameraInfo.from(info)

            fun <T> char(key: CameraCharacteristics.Key<T>): T? = try {
                c2.getCameraCharacteristic(key)
            } catch (_: Exception) {
                null
            }

            val level = when (char(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)) {
                CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY -> "LEGACY"
                CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED -> "LIMITED"
                CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_FULL -> "FULL"
                CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_3 -> "LEVEL_3"
                CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL -> "EXTERNAL"
                else -> LEVEL_UNKNOWN
            }

            val caps = char(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)
                ?.toSet()
                .orEmpty()
            val manualSensor =
                CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR in caps
            val raw = CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_RAW in caps

            val expRange = char(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
            val isoRange = char(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
            val minFocus = char(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE)

            // A fixed-focus lens reports 0.0 as its near limit: it can only ever
            // focus at infinity, so there is nothing to drive manually.
            val manualFocus = minFocus != null && minFocus > 0f

            val ois = char(CameraCharacteristics.LENS_INFO_AVAILABLE_OPTICAL_STABILIZATION)
                ?.any { it == CameraMetadata.LENS_OPTICAL_STABILIZATION_MODE_ON }
                ?: false

            val dng = try {
                ImageCapture.getImageCaptureCapabilities(info)
                    .supportedOutputFormats
                    .contains(ImageCapture.OUTPUT_FORMAT_RAW)
            } catch (_: Exception) {
                false
            }

            // Optics for the exposure advisor. Each is independently nullable:
            // a device that reports focal length but not aperture should still
            // yield what it knows, and the advisor simply declines rather than
            // substituting a plausible-looking constant.
            val focalMm = char(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
                ?.firstOrNull()
                ?.takeIf { it > 0f }
            val aperture = char(CameraCharacteristics.LENS_INFO_AVAILABLE_APERTURES)
                ?.firstOrNull()
                ?.takeIf { it > 0f }
            // Pixel pitch is not reported directly: it is the sensor's physical
            // width divided by its pixel count, converted mm -> um.
            val physical = char(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
            val arraySize = char(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE)
            val pitchUm = if (physical != null && arraySize != null && arraySize.width > 0) {
                (physical.width / arraySize.width * 1000f).takeIf { it > 0f }
            } else {
                null
            }

            return CameraCapabilities(
                hardwareLevel = level,
                // Check the capability flag as well as the level: the flag is
                // what actually governs whether SENSOR_EXPOSURE_TIME is honoured.
                manualSensorSupported = manualSensor &&
                    (level == "FULL" || level == "LEVEL_3"),
                exposureMinNs = expRange?.lower ?: 0L,
                // ~1/30 s if unreported: low enough to look obviously wrong in
                // the UI rather than silently permitting a long exposure the
                // driver would quietly truncate.
                exposureMaxNs = expRange?.upper ?: 33_000_000L,
                isoMin = isoRange?.lower ?: 100,
                isoMax = isoRange?.upper ?: 800,
                maxAnalogIso = char(CameraCharacteristics.SENSOR_MAX_ANALOG_SENSITIVITY),
                rawCapable = raw,
                dngSupported = dng && raw,
                manualFocusSupported = manualFocus,
                minFocusDistanceDioptres = minFocus,
                oisSupported = ois,
                focalLengthMm = focalMm,
                fNumber = aperture,
                pixelPitchUm = pitchUm,
            )
        }
    }
}

/**
 * The measured outcome of pushing exposure past what the sensor advertises.
 *
 * [CameraCapabilities.exposureMaxNs] is what `SENSOR_INFO_EXPOSURE_TIME_RANGE`
 * reports, and on several devices it is conservative rather than enforced --
 * DeepSkyCamera documents 17 s on a Pixel 7 Pro that advertises 8.3 s, obtained
 * through plain Camera2. Doubling the sub length halves frame count, storage,
 * total read noise and thermal duty cycle, so it is worth having.
 *
 * What makes this safe rather than reckless: the value is *measured* on the
 * specific device, and every captured frame's achieved exposure is read back
 * from `CaptureResult` and compared (see [exposureWithinTolerance]). Blind
 * over-requesting -- asking for more and hoping -- is the bug this type exists
 * to avoid.
 */
data class ExposureCalibration(
    /** What the sensor claimed before calibration, nanoseconds. */
    val advertisedMaxNs: Long,
    /** Longest exposure the sensor actually delivered, nanoseconds. */
    val measuredMaxNs: Long,
    /** True once a real capture confirmed [measuredMaxNs]. */
    val verified: Boolean,
) {
    /** True when the sensor beat its own advertisement by a useful margin. */
    val extended: Boolean
        get() = verified && measuredMaxNs > (advertisedMaxNs * EXTENSION_MARGIN).toLong()

    /**
     * The exposure ceiling the UI should offer.
     *
     * Falls back to the advertised value unless calibration both ran and found
     * something better -- the conservative direction, so a failed or absent
     * calibration can never lengthen an exposure.
     */
    val usableMaxNs: Long get() = if (extended) measuredMaxNs else advertisedMaxNs

    companion object {
        /** Ignore extensions under 10%: within measurement noise, not worth the risk. */
        const val EXTENSION_MARGIN = 1.10

        /**
         * Requested-vs-achieved tolerance. Beyond this, the frame is not the
         * exposure the user asked for and the sequence must stop.
         */
        const val TOLERANCE = 0.05

        /**
         * Exposures to try, nanoseconds: 8 s through 30 s.
         *
         * Starts just under the common ~8.3 s advertisement and stops at 30 s,
         * past any plausible phone ceiling. The walk halts at the first failure,
         * so the upper entries cost nothing on a device that caps early.
         */
        val PROBE_STEPS_NS: List<Long> =
            listOf(8L, 10L, 12L, 14L, 16L, 17L, 18L, 20L, 25L, 30L)
                .map { it * 1_000_000_000L }

        /** An uncalibrated result: trust only what the sensor advertised. */
        fun untested(advertisedMaxNs: Long) = ExposureCalibration(
            advertisedMaxNs = advertisedMaxNs,
            measuredMaxNs = advertisedMaxNs,
            verified = false,
        )
    }
}

/**
 * True when an achieved exposure is close enough to what was requested.
 *
 * The guard behind the whole extension approach: a silently truncated frame in a
 * sequence the user believes is running at 17 s is exactly the failure mode that
 * makes blind over-requesting unacceptable. Checked on every frame, whether or
 * not the extension is enabled.
 */
fun exposureWithinTolerance(requestedNs: Long, achievedNs: Long): Boolean {
    if (requestedNs <= 0L) return false
    return abs(achievedNs - requestedNs).toDouble() / requestedNs <= ExposureCalibration.TOLERANCE
}

/**
 * Horizontal and vertical field of view in degrees, from the lens's real optics.
 *
 * Pinhole small-angle approximation over the camera2 focal length and physical
 * sensor size. Returns (long axis, short axis); in portrait the sensor's long
 * axis maps to the screen vertical. Null when the characteristics are
 * unreadable, in which case callers keep their own default.
 *
 * Shared by the horizon reticle, which maps degrees to pixels for its graticule,
 * and the Shoot tab.
 */
@OptIn(ExperimentalCamera2Interop::class)
fun readFov(info: CameraInfo): Pair<Float, Float>? = try {
    val c2 = Camera2CameraInfo.from(info)
    val focal = c2.getCameraCharacteristic(
        CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS,
    )?.firstOrNull()
    val sensor = c2.getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
    if (focal != null && sensor != null && focal > 0f) {
        val long = Math.toDegrees(2.0 * atan(sensor.width / (2.0 * focal))).toFloat()
        val short = Math.toDegrees(2.0 * atan(sensor.height / (2.0 * focal))).toFloat()
        long to short
    } else {
        null
    }
} catch (_: Exception) {
    null
}
