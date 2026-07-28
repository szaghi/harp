package org.szaghi.harp

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.Locale
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.roundToInt
import kotlin.math.roundToLong
import kotlin.math.sqrt

/**
 * A live histogram of the preview luminance, plus the framing aids computed from
 * the same pass.
 *
 * One walk over the Y plane feeds everything: building the histogram and the
 * focus-peaking measure separately would double the per-frame cost for no gain.
 *
 * @property bins [BIN_COUNT] buckets over the 0..255 luminance range
 * @property peakBin brightest populated bucket -- the clipping check
 * @property backgroundBin modal bucket, i.e. where the sky sits
 * @property focusScore mean gradient magnitude; higher is sharper
 */
data class PreviewStats(
    val bins: IntArray = IntArray(BIN_COUNT),
    val peakBin: Int = 0,
    val backgroundBin: Int = 0,
    val focusScore: Float = 0f,
) {
    /**
     * True when the sky background sits in the useful band.
     *
     * A sub wants the background far enough off the floor to swamp read noise,
     * but not so high that it eats dynamic range: roughly a fifth to a third up
     * the histogram. This is the single number telling the user their ISO is
     * right, and it is why the histogram earns its per-frame cost.
     */
    val backgroundOk: Boolean
        get() = backgroundBin in (BIN_COUNT / 5)..(BIN_COUNT / 3)

    /** True when the highlights are against the ceiling. */
    val clipping: Boolean get() = peakBin >= BIN_COUNT - 1

    // IntArray in a data class needs content-based equals/hashCode, or Compose
    // sees every frame as a new value even when the numbers are identical.
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is PreviewStats) return false
        return bins.contentEquals(other.bins) &&
            peakBin == other.peakBin &&
            backgroundBin == other.backgroundBin &&
            focusScore == other.focusScore
    }

    override fun hashCode(): Int {
        var r = bins.contentHashCode()
        r = 31 * r + peakBin
        r = 31 * r + backgroundBin
        r = 31 * r + focusScore.hashCode()
        return r
    }

    companion object {
        const val BIN_COUNT = 64
    }
}

/**
 * A recommendation from `shoot_bridge.advise()`, plus the reasoning behind it.
 *
 * [iso] is nullable on purpose and mirrors the Python side: when the selected
 * site declares neither Bortle class nor SQM there is no sky brightness to
 * solve against, and :mod:`harp.sky` returns nothing rather than a guess. The
 * exposure advice still stands, so the card shows what it knows and says why
 * the rest is missing -- a fabricated ISO would be worse than an absent one.
 */
data class ExposureAdvice(
    val exposureS: Double,
    val iso: Int?,
    val frames: Int,
    val storageBytes: Long,
    val fitsWindow: Boolean?,
    val skyMag: Double?,
    val reasons: List<String>,
) {
    /** True when the site lacks the sky data an ISO recommendation needs. */
    val needsSkyQuality: Boolean get() = iso == null
}

/** Where the advisor call has got to. */
sealed interface AdviceState {
    data object Idle : AdviceState

    data object Running : AdviceState

    data class Ready(val advice: ExposureAdvice) : AdviceState

    data class Failed(val reason: String) : AdviceState
}

/** Which channel the single stop wheel is currently driving. */
enum class WheelChannel { NONE, EXPOSURE, ISO }

/** Where the exposure-calibration probe has got to. */
sealed interface CalibrationState {
    data object Idle : CalibrationState

    data class Running(val stepSec: Double) : CalibrationState

    data class Done(val calibration: ExposureCalibration) : CalibrationState

    data class Failed(val reason: String) : CalibrationState
}

/**
 * State and settings for the Shoot tab.
 *
 * Holds the manual capture settings, the probed device capabilities and the live
 * preview statistics. The camera binding itself lives in [CaptureController]:
 * this class decides *what* to shoot, not *how* to talk to the sensor.
 */
class ShootViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = SettingsRepo(app)
    private val sitesRepo = SitesRepo(app)

    private val _caps = MutableStateFlow<CameraCapabilities?>(null)
    val caps: StateFlow<CameraCapabilities?> = _caps.asStateFlow()

    private val _stats = MutableStateFlow(PreviewStats())
    val stats: StateFlow<PreviewStats> = _stats.asStateFlow()

    private val _calibration = MutableStateFlow<CalibrationState>(CalibrationState.Idle)
    val calibration: StateFlow<CalibrationState> = _calibration.asStateFlow()

    private val _lastShot = MutableStateFlow<CaptureOutcome?>(null)
    val lastShot: StateFlow<CaptureOutcome?> = _lastShot.asStateFlow()

    /** Requested exposure, nanoseconds; clamped to the usable ceiling. */
    private val _exposureNs = MutableStateFlow(0L)
    val exposureNs: StateFlow<Long> = _exposureNs.asStateFlow()

    private val _iso = MutableStateFlow(0)
    val iso: StateFlow<Int> = _iso.asStateFlow()

    /** 0.0 is infinity -- the default, and usually the right answer for stars. */
    private val _focusDioptres = MutableStateFlow(0f)
    val focusDioptres: StateFlow<Float> = _focusDioptres.asStateFlow()

    /** Display-only preview brightening; never touches the captured frame. */
    private val _previewGain = MutableStateFlow(4f)
    val previewGain: StateFlow<Float> = _previewGain.asStateFlow()

    private val _focusPeaking = MutableStateFlow(true)
    val focusPeaking: StateFlow<Boolean> = _focusPeaking.asStateFlow()

    // --- Sequence settings --------------------------------------------------
    // These live here rather than in the composable so they survive both
    // rotation and process death; previously they were remember{} state inside
    // ShootScreen and were lost on every recreation.

    private val _sessionName = MutableStateFlow("")
    val sessionName: StateFlow<String> = _sessionName.asStateFlow()

    private val _durationMin = MutableStateFlow(60)
    val durationMin: StateFlow<Int> = _durationMin.asStateFlow()

    private val _startDelaySec = MutableStateFlow(5)
    val startDelaySec: StateFlow<Int> = _startDelaySec.asStateFlow()

    private val _ditherEvery = MutableStateFlow(0)
    val ditherEvery: StateFlow<Int> = _ditherEvery.asStateFlow()

    // --- Wheel + focus mode -------------------------------------------------

    private val _channel = MutableStateFlow(WheelChannel.NONE)
    val channel: StateFlow<WheelChannel> = _channel.asStateFlow()

    private val _focusMode = MutableStateFlow(false)
    val focusMode: StateFlow<Boolean> = _focusMode.asStateFlow()

    /**
     * Recent focus scores, oldest first.
     *
     * Focusing is a hill climb: the absolute number means little, but its
     * *trend* tells you which way to turn and, crucially, when you have gone
     * past the peak. A single live value cannot show that -- by the time it
     * falls you have already lost the maximum and have nothing to return to.
     */
    private val _focusTrace = MutableStateFlow<List<Float>>(emptyList())
    val focusTrace: StateFlow<List<Float>> = _focusTrace.asStateFlow()

    private val _adviceState = MutableStateFlow<AdviceState>(AdviceState.Idle)
    val adviceState: StateFlow<AdviceState> = _adviceState.asStateFlow()

    private var storedCalibrationNs = 0L
    private var extendedEnabled = false

    /** True once the first settings emission has seeded the in-memory state. */
    private var restored = false

    init {
        // Restore last-used settings so the tab reopens where it was left.
        //
        // Only the first emission seeds the state: later emissions are this
        // class's own writes arriving back, and re-applying them would fight a
        // control the user is currently dragging.
        viewModelScope.launch {
            repo.flow.collect { s ->
                storedCalibrationNs = s.exposureCalibratedNs
                extendedEnabled = s.extendedExposure
                if (_exposureNs.value == 0L && s.shootExposureNs > 0L) {
                    _exposureNs.value = s.shootExposureNs
                }
                if (_iso.value == 0 && s.shootIso > 0) _iso.value = s.shootIso
                if (!restored) {
                    restored = true
                    _focusDioptres.value = s.shootFocusDioptres
                    _previewGain.value = s.shootPreviewGain
                    _focusPeaking.value = s.shootPeaking
                    _sessionName.value = s.shootSessionName
                    _durationMin.value = s.shootDurationMin
                    _startDelaySec.value = s.shootStartDelaySec
                    _ditherEvery.value = s.shootDitherEvery
                }
            }
        }
    }

    /**
     * The longest exposure the UI may offer.
     *
     * Falls back to the advertised maximum unless calibration both ran and found
     * a real improvement *and* the user opted in. Conservative by construction:
     * a stale or failed calibration can never lengthen a frame.
     */
    fun usableMaxExposureNs(): Long {
        val advertised = _caps.value?.exposureMaxNs ?: 0L
        if (!extendedEnabled || storedCalibrationNs <= 0L) return advertised
        return ExposureCalibration(advertised, storedCalibrationNs, verified = true).usableMaxNs
    }

    /** Record the probe result and seed sensible defaults for this device. */
    fun onCapabilities(c: CameraCapabilities) {
        _caps.value = c
        if (_exposureNs.value == 0L) _exposureNs.value = usableMaxExposureNs()
        if (_iso.value == 0) _iso.value = defaultIso(c)
    }

    /**
     * A sane starting ISO: the analog ceiling, or two thirds up without one.
     *
     * Analog gain is real signal; digital gain above
     * [CameraCapabilities.maxAnalogIso] only amplifies noise, so there is no
     * reason to start above it.
     */
    private fun defaultIso(c: CameraCapabilities): Int =
        c.maxAnalogIso ?: (c.isoMin + (c.isoMax - c.isoMin) * 2 / 3)

    fun setExposureNs(ns: Long) {
        val caps = _caps.value ?: return
        _exposureNs.value = ns.coerceIn(caps.exposureMinNs, usableMaxExposureNs())
        persist(SettingsRepo.SHOOT_EXPOSURE_NS, _exposureNs.value)
    }

    fun setIso(v: Int) {
        val caps = _caps.value ?: return
        _iso.value = v.coerceIn(caps.isoMin, caps.isoMax)
        persist(SettingsRepo.SHOOT_ISO, _iso.value)
    }

    fun setFocusDioptres(d: Float) {
        val maxD = _caps.value?.minFocusDistanceDioptres ?: 0f
        _focusDioptres.value = d.coerceIn(0f, maxD)
        persist(SettingsRepo.SHOOT_FOCUS_DIOPTRES, _focusDioptres.value)
    }

    /** Snap to infinity: the correct starting point for every astro frame. */
    fun focusInfinity() {
        _focusDioptres.value = 0f
        persist(SettingsRepo.SHOOT_FOCUS_DIOPTRES, 0f)
    }

    fun setPreviewGain(g: Float) {
        _previewGain.value = g.coerceIn(1f, 16f)
        persist(SettingsRepo.SHOOT_PREVIEW_GAIN, _previewGain.value)
    }

    fun toggleFocusPeaking() {
        _focusPeaking.value = !_focusPeaking.value
        persist(SettingsRepo.SHOOT_PEAKING, _focusPeaking.value)
    }

    // --- Sequence setters ---------------------------------------------------

    fun setSessionName(v: String) {
        _sessionName.value = v
        persist(SettingsRepo.SHOOT_SESSION_NAME, v)
    }

    fun setDurationMin(v: Int) {
        _durationMin.value = v.coerceIn(MIN_DURATION_MIN, MAX_DURATION_MIN)
        persist(SettingsRepo.SHOOT_DURATION_MIN, _durationMin.value)
    }

    fun setStartDelaySec(v: Int) {
        _startDelaySec.value = v.coerceIn(0, MAX_START_DELAY_SEC)
        persist(SettingsRepo.SHOOT_START_DELAY_SEC, _startDelaySec.value)
    }

    fun setDitherEvery(v: Int) {
        _ditherEvery.value = v.coerceAtLeast(0)
        persist(SettingsRepo.SHOOT_DITHER_EVERY, _ditherEvery.value)
    }

    private fun <T> persist(key: androidx.datastore.preferences.core.Preferences.Key<T>, v: T) {
        viewModelScope.launch { repo.set(key, v) }
    }

    fun settings(): CaptureSettings = CaptureSettings(
        exposureNs = _exposureNs.value,
        iso = _iso.value,
        focusDioptres = _focusDioptres.value,
        dng = _caps.value?.dngSupported ?: false,
    )

    fun onStats(s: PreviewStats) {
        _stats.value = s
        // Only trace while focusing: the buffer exists to be read against a
        // slider the user is turning right now, and keeping it fed for the
        // whole session would just cost allocations nobody looks at.
        if (_focusMode.value) {
            _focusTrace.value = (_focusTrace.value + s.focusScore).takeLast(FOCUS_TRACE_LEN)
        }
    }

    fun setChannel(c: WheelChannel) {
        // Tapping the active chip closes the wheel, giving the preview back.
        _channel.value = if (_channel.value == c) WheelChannel.NONE else c
    }

    fun enterFocusMode() {
        _focusTrace.value = emptyList()
        _channel.value = WheelChannel.NONE
        _focusMode.value = true
    }

    fun exitFocusMode() {
        _focusMode.value = false
    }

    /** Index of the best score in the current trace, or -1 when it is empty. */
    fun focusPeakIndex(): Int {
        val t = _focusTrace.value
        if (t.isEmpty()) return -1
        var best = 0
        for (i in t.indices) if (t[i] > t[best]) best = i
        return best
    }

    fun onShot(o: CaptureOutcome) {
        _lastShot.value = o
    }

    fun setCalibrationState(s: CalibrationState) {
        _calibration.value = s
    }

    /**
     * Ask the shared Python core what to shoot, and why.
     *
     * The reasoning matters as much as the numbers: this is the difference
     * between an assistant that hands down settings and one that teaches the
     * user enough to adapt when conditions change. Runs off the main thread --
     * it crosses into Chaquopy and touches the catalog-backed sky model.
     *
     * Resolves the observing site the same way the planner does: the selected
     * saved site, else the store default. A site's declared sky quality is what
     * makes an ISO recommendation possible at all; without one the advisor
     * still returns an exposure and says why the rest is missing.
     */
    fun requestAdvice(tracked: Boolean = true) {
        val c = _caps.value ?: return
        if (!c.opticsKnown) {
            _adviceState.value = AdviceState.Failed(
                "This camera does not report its focal length, aperture or pixel " +
                    "size, so exposure cannot be advised.",
            )
            return
        }
        _adviceState.value = AdviceState.Running
        val integrationHours = _durationMin.value / 60.0
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val site = selectedSite()
                    val kwargs = mutableMapOf<String, Any?>(
                        "focal_mm" to c.focalLengthMm,
                        "f_number" to c.fNumber,
                        "pixel_pitch_um" to c.pixelPitchUm,
                        "iso_min" to c.isoMin,
                        "iso_max" to c.isoMax,
                        "max_analog_iso" to c.maxAnalogIso,
                        "max_exposure_s" to usableMaxExposureNs() / 1_000_000_000.0,
                        "tracked" to tracked,
                        "bortle" to site?.bortle,
                        "sqm" to site?.sqm,
                        "integration_hours" to integrationHours,
                    )
                    val py = PyBridge.py.getModule("shoot_bridge")
                    val out = py.callAttr("advise_json", JSONObject(kwargs).toString())
                    JSONObject(out.toString())
                }
            }
            _adviceState.value = result.fold(
                onSuccess = { obj ->
                    // The bridge reports failure in-band rather than raising,
                    // because a Python exception crossing JNI arrives with no
                    // usable message.
                    val err = obj.optString("error", "")
                    if (err.isNotEmpty()) {
                        AdviceState.Failed(err)
                    } else {
                        AdviceState.Ready(parseAdvice(obj))
                    }
                },
                onFailure = { AdviceState.Failed(it.message ?: "advisor failed") },
            )
        }
    }

    /**
     * The site the plan would use: the selected one, else the store default.
     *
     * Null when neither exists -- the GPS-fallback case, which has no saved
     * site and therefore no declared sky quality.
     */
    private suspend fun selectedSite(): SiteUi? = runCatching {
        val selected = repo.flow.first().selectedSite
        val (_, sites) = sitesRepo.list()
        sites.firstOrNull { it.name == selected } ?: sites.firstOrNull { it.isDefault }
    }.getOrNull()

    /** Adopt the advisor's numbers. ISO is skipped when the sky was unknown. */
    fun applyAdvice(a: ExposureAdvice) {
        setExposureNs((a.exposureS * 1_000_000_000.0).toLong())
        a.iso?.let { setIso(it) }
    }

    fun dismissAdvice() {
        _adviceState.value = AdviceState.Idle
    }

    /** Persist a completed calibration and enable the extension if it earned it. */
    fun saveCalibration(c: ExposureCalibration) {
        _calibration.value = CalibrationState.Done(c)
        storedCalibrationNs = c.measuredMaxNs
        extendedEnabled = c.extended
        viewModelScope.launch {
            repo.set(SettingsRepo.EXPOSURE_CALIBRATED_NS, c.measuredMaxNs)
            repo.set(SettingsRepo.EXTENDED_EXPOSURE, c.extended)
        }
    }

    /**
     * Read the advisor's JSON into [ExposureAdvice].
     *
     * `iso` and `fits_window` are genuinely nullable on the Python side, so
     * `isNull` is checked rather than relying on `optInt`'s zero default -- ISO
     * 0 would be indistinguishable from "the sky is unknown".
     */
    private fun parseAdvice(o: JSONObject): ExposureAdvice {
        val reasons = buildList {
            val arr = o.optJSONArray("reasons") ?: return@buildList
            for (i in 0 until arr.length()) add(arr.getString(i))
        }
        return ExposureAdvice(
            exposureS = o.optDouble("exposure_s", 0.0),
            iso = if (o.isNull("iso")) null else o.optInt("iso"),
            frames = o.optInt("frames", 0),
            storageBytes = o.optLong("storage_bytes", 0L),
            fitsWindow = if (o.isNull("fits_window")) null else o.optBoolean("fits_window"),
            skyMag = if (o.isNull("sky_mag")) null else o.optDouble("sky_mag"),
            reasons = reasons,
        )
    }

    companion object {
        /**
         * Focus-trace length.
         *
         * Long enough to hold a full sweep through best focus at preview frame
         * rate, short enough that the peak stays on screen while you tune.
         */
        const val FOCUS_TRACE_LEN = 64

        /**
         * Sequence duration bounds, minutes.
         *
         * Below ten minutes there is nothing worth automating; above three
         * hours the phone runs out of battery and thermal headroom long before
         * the sky runs out of target.
         */
        const val MIN_DURATION_MIN = 10
        const val MAX_DURATION_MIN = 180

        /** Longest settle delay before frame 1, seconds. */
        const val MAX_START_DELAY_SEC = 60

        /**
         * Map a 0..1 slider position onto an exposure, logarithmically.
         *
         * Exposure is perceived in stops, so a linear slider wastes most of its
         * travel on the long end: from 1/30 s to 8 s, half a linear track sits
         * above 4 s. Log spacing gives every stop equal room.
         */
        fun sliderToExposureNs(pos: Float, minNs: Long, maxNs: Long): Long {
            if (minNs <= 0L || maxNs <= minNs) return maxNs
            val lo = ln(minNs.toDouble())
            val hi = ln(maxNs.toDouble())
            return exp(lo + (hi - lo) * pos.coerceIn(0f, 1f)).roundToLong()
        }

        /** Inverse of [sliderToExposureNs], for positioning the thumb. */
        fun exposureNsToSlider(ns: Long, minNs: Long, maxNs: Long): Float {
            if (minNs <= 0L || maxNs <= minNs || ns <= 0L) return 1f
            val lo = ln(minNs.toDouble())
            val hi = ln(maxNs.toDouble())
            return ((ln(ns.toDouble()) - lo) / (hi - lo)).toFloat().coerceIn(0f, 1f)
        }

        /**
         * Map a 0..1 slider onto focus dioptres with a squared response.
         *
         * The useful astro range is compressed into the last few percent of the
         * dioptre scale -- everything from a few metres to infinity lives there.
         * A linear slider makes infinity focus untunable; squaring gives the
         * near-infinity end most of the travel.
         */
        fun sliderToDioptres(pos: Float, maxD: Float): Float {
            val p = pos.coerceIn(0f, 1f)
            return p * p * maxD
        }

        /** Inverse of [sliderToDioptres]. */
        fun dioptresToSlider(d: Float, maxD: Float): Float {
            if (maxD <= 0f) return 0f
            return sqrt((d / maxD).coerceIn(0f, 1f))
        }

        /** Human-readable exposure: "1/60 s" when short, "8.3 s" when long. */
        fun formatExposure(ns: Long): String {
            if (ns <= 0L) return "--"
            val sec = ns / 1_000_000_000.0
            return if (sec >= 1.0) {
                String.format(Locale.US, "%.1f s", sec)
            } else {
                "1/${(1.0 / sec).roundToInt()} s"
            }
        }
    }
}
