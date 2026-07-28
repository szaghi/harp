package org.szaghi.harp

import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * A discrete value the stop wheel can land on.
 *
 * @property value the setting itself -- nanoseconds for exposure, ISO for gain
 * @property label what the wheel prints on the tick
 * @property major whole stops, which carry a label; intermediates do not
 * @property calibrationGated true when the value exceeds what the sensor
 *   *advertises* and is reachable only because [ExposureCalibration] measured
 *   it. Drawn differently, because offering it as an ordinary stop would claim
 *   a guarantee the hardware never gave.
 */
data class Stop(
    val value: Long,
    val label: String,
    val major: Boolean,
    val calibrationGated: Boolean = false,
)

/**
 * An ordered ladder of stops the wheel can select from.
 *
 * Camera2 reports *ranges*, not enumerations: `SENSOR_INFO_EXPOSURE_TIME_RANGE`
 * and `SENSOR_INFO_SENSITIVITY_RANGE` are continuous. So a "real stop" is a
 * convention this file defines, clamped to what the device will actually
 * accept -- not something the sensor hands us. Values outside the reported
 * range are dropped rather than greyed: a tick that can never be selected is
 * noise on a control operated in the dark.
 */
data class StopLadder(
    val stops: List<Stop>,
) {
    val size: Int get() = stops.size

    /** Index of the stop nearest [value]; 0 when the ladder is empty. */
    fun nearestIndex(value: Long): Int {
        if (stops.isEmpty()) return 0
        var best = 0
        var bestDelta = Long.MAX_VALUE
        for (i in stops.indices) {
            val d = abs(stops[i].value - value)
            if (d < bestDelta) {
                bestDelta = d
                best = i
            }
        }
        return best
    }

    operator fun get(i: Int): Stop = stops[i.coerceIn(0, stops.size - 1)]

    companion object {
        /**
         * Canonical exposure ladder, nanoseconds.
         *
         * Whole stops from 1/1000 s up, densest at the long end where astro
         * work lives. Anything outside the device's reported range is filtered
         * out by [forExposure].
         */
        private val EXPOSURE_STEPS_NS: List<Pair<Long, Boolean>> = listOf(
            1_000_000L to true, // 1/1000
            2_000_000L to false,
            4_000_000L to true, // 1/250
            8_000_000L to false,
            16_666_666L to true, // 1/60
            33_333_333L to false, // 1/30
            66_666_666L to true, // 1/15
            125_000_000L to false, // 1/8
            250_000_000L to true, // 1/4
            500_000_000L to false, // 1/2
            1_000_000_000L to true,
            1_500_000_000L to false,
            2_000_000_000L to true,
            3_000_000_000L to false,
            4_000_000_000L to true,
            6_000_000_000L to false,
            8_000_000_000L to true,
            10_000_000_000L to false,
            12_000_000_000L to true,
            15_000_000_000L to false,
            17_000_000_000L to true,
            20_000_000_000L to false,
            25_000_000_000L to true,
            30_000_000_000L to false,
        )

        /** Canonical ISO ladder: thirds of a stop through the usual range. */
        private val ISO_STEPS: List<Pair<Int, Boolean>> = listOf(
            50 to true,
            64 to false,
            80 to false,
            100 to true,
            125 to false,
            160 to false,
            200 to true,
            250 to false,
            320 to false,
            400 to true,
            500 to false,
            640 to false,
            800 to true,
            1000 to false,
            1250 to false,
            1600 to true,
            2000 to false,
            2500 to false,
            3200 to true,
            4000 to false,
            5000 to false,
            6400 to true,
            12800 to true,
        )

        /**
         * The exposure ladder this device can actually deliver.
         *
         * [advertisedMaxNs] is the sensor's own claim; [usableMaxNs] may exceed
         * it when calibration measured more (see [ExposureCalibration]). Stops
         * between the two are kept but flagged, so the UI can show that they
         * rest on a measurement rather than on the sensor's word.
         */
        fun forExposure(
            minNs: Long,
            advertisedMaxNs: Long,
            usableMaxNs: Long,
        ): StopLadder {
            val ceiling = maxOf(advertisedMaxNs, usableMaxNs)
            val kept = EXPOSURE_STEPS_NS
                .filter { (ns, _) -> ns in minNs..ceiling }
                .map { (ns, major) ->
                    Stop(
                        value = ns,
                        label = formatExposureLabel(ns),
                        major = major,
                        calibrationGated = ns > advertisedMaxNs,
                    )
                }
            // A device whose entire range falls between two canonical steps
            // would otherwise get an empty ladder and an inoperable wheel.
            val stops = kept.ifEmpty {
                listOf(Stop(usableMaxNs, formatExposureLabel(usableMaxNs), major = true))
            }
            return StopLadder(stops)
        }

        /**
         * The ISO ladder, stopping at the analog ceiling when one is reported.
         *
         * Above [CameraCapabilities.maxAnalogIso] the sensor multiplies after
         * the ADC: noise and signal rise together while highlight headroom is
         * spent, achieving nothing a later stretch could not. Offering those
         * values would invite a choice with no upside.
         */
        fun forIso(minIso: Int, maxIso: Int, maxAnalogIso: Int?): StopLadder {
            val ceiling = maxAnalogIso?.let { minOf(maxIso, it) } ?: maxIso
            val kept = ISO_STEPS
                .filter { (iso, _) -> iso in minIso..ceiling }
                .map { (iso, major) ->
                    Stop(value = iso.toLong(), label = iso.toString(), major = major)
                }
            val stops = kept.ifEmpty {
                listOf(Stop(ceiling.toLong(), ceiling.toString(), major = true))
            }
            return StopLadder(stops)
        }

        /**
         * Session-length ladder, minutes.
         *
         * Coarser as it lengthens: the difference between 20 and 25 minutes
         * matters, the difference between 150 and 155 does not.
         */
        fun forDurationMinutes(): StopLadder = StopLadder(
            listOf(
                10 to false, 15 to true, 20 to false, 30 to true, 45 to false,
                60 to true, 75 to false, 90 to true, 120 to true, 150 to false,
                180 to true,
            ).map { (m, major) -> Stop(m.toLong(), formatMinutes(m), major) },
        )

        /** Start-delay ladder, seconds: settle time before the first frame. */
        fun forStartDelaySeconds(): StopLadder = StopLadder(
            listOf(
                0 to true, 2 to false, 5 to true, 10 to false, 15 to true,
                20 to false, 30 to true, 45 to false, 60 to true,
            ).map { (s, major) -> Stop(s.toLong(), "${s}s", major) },
        )

        /**
         * Dither cadence: pause every N frames for a manual nudge.
         *
         * Zero is a real choice, not an absent one, so it gets a tick labelled
         * "off" rather than being expressed by the wheel's absence.
         */
        fun forDitherEvery(): StopLadder = StopLadder(
            listOf(
                0 to true, 5 to false, 10 to true, 20 to false, 30 to true,
                50 to false, 100 to true,
            ).map { (n, major) -> Stop(n.toLong(), if (n == 0) "off" else n.toString(), major) },
        )

        /**
         * Exposure as a photographer reads it: "1/60" when short, "8.3s" when long.
         *
         * Locale.US throughout -- on an it_IT device the default would render
         * "8,3" where every other number in this UI uses a decimal point.
         */
        fun formatExposureLabel(ns: Long): String {
            if (ns <= 0L) return "--"
            val sec = ns / 1_000_000_000.0
            return when {
                sec >= 10.0 -> String.format(Locale.US, "%.0fs", sec)
                sec >= 1.0 -> String.format(Locale.US, "%.1fs", sec)
                else -> "1/${(1.0 / sec).roundToInt()}"
            }
        }

        /** "45m" / "1h" / "1h30" -- compact enough for a tick label. */
        fun formatMinutes(m: Int): String {
            if (m < 60) return "${m}m"
            val h = m / 60
            val rem = m % 60
            return if (rem == 0) "${h}h" else "${h}h$rem"
        }
    }
}
