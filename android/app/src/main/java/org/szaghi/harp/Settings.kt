package org.szaghi.harp

import android.app.Application
import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

private val Context.dataStore by preferencesDataStore(name = "harp_settings")

/** Persisted app configuration: the on-device mirror of the CLI options. */
data class AppSettings(
    val focal: Float = 800f,
    val sensor: String = "23.5x15.7",
    val overlap: Float = 0.15f,
    val minHours: Float = 1f,
    val minPeakAlt: Float = 20f,
    val moonSep: Float = 30f,
    val magLimit: Float = 11f,
    val top: Int = 30,
    val sortByScore: Boolean = true,
    val gridMin: Int = 10,
    val catalogs: String = "M", // "M" | "M,NGC" | "M,NGC,IC"
    val linkSite: String = "simbad",
    // Selected saved site (name/slug in the sites store); "" means none
    // selected yet -> the store's default_site is used, GPS as last resort.
    val selectedSite: String = "",
    // Appearance. nightVision toggles the red field mode (overrides the indoor
    // pick); indoorTheme is the chosen indoor palette id (see INDOOR_THEMES).
    val nightVision: Boolean = false,
    val indoorTheme: String = DEFAULT_INDOOR_THEME,
    // Include Solar System bodies (Moon + planets) in the plan; on by default,
    // matching the CLI.
    val solarSystem: Boolean = true,
    // Include the Sharpless (Sh2) H II regions and their measured sizes; on by
    // default, matching the CLI.
    val sharpless: Boolean = true,
    // Include currently observable comets, positioned from MPC orbital elements
    // fetched at run time. OFF by default: this is the only online part of a
    // plan, so opting in is deliberate. cometMagLimit drops comets predicted
    // fainter than this apparent magnitude tonight (12 hides the unimageable).
    val comets: Boolean = false,
    val cometMagLimit: Float = 12f,
    // Minimum Sharpless angular diameter to keep, arcmin (matches the CLI's
    // --sharpless-min-diam; drops tiny/compact H II regions).
    val sharplessMinDiam: Float = 10f,
    // Atmospheric conditions for the polar-alignment refraction correction
    // (reticle stage). Defaults match harp.polar's own (1010 hPa / 10 C).
    // Their effect is sub-arcminute for realistic values, so this is a
    // refinement for the fastidious, not a required input.
    val pressureHpa: Float = 1010f,
    val tempC: Float = 10f,
    // --- Shoot tab ---------------------------------------------------------
    // Measured longest exposure the sensor actually delivered, nanoseconds; 0
    // means "never calibrated". Persisted because the probe is a one-off: it
    // costs a minute of real captures, and re-running it every launch would be
    // rude. See ExposureCalibration for why measuring beats trusting the
    // advertised range.
    val exposureCalibratedNs: Long = 0L,
    // Opt-in to exposures beyond what the sensor advertises. Off until the
    // probe has both run and found a real improvement -- the conservative
    // direction, so a stale or failed calibration can never lengthen a frame.
    val extendedExposure: Boolean = false,
    // Last-used capture settings, so the tab reopens where the user left it.
    val shootExposureNs: Long = 0L, // 0 = use the calibrated/advertised maximum
    val shootIso: Int = 0, // 0 = use the advisor's suggestion
    // Focus in dioptres; 0.0 is infinity, which is both the default and the
    // right answer for almost every astro frame.
    val shootFocusDioptres: Float = 0f,
    // Display-only preview brightening. Persisted because the value a user
    // settles on is a property of their eyes and their sky, not of one session.
    val shootPreviewGain: Float = 4f,
    val shootPeaking: Boolean = true,
    // --- Sequence (intervalometer) -----------------------------------------
    // Persisted for the same reason as the capture settings: a sequence
    // interrupted by a dead battery or a stray back-press should not also cost
    // the user the setup they typed in the dark. An empty name means "derive
    // one from the selected target".
    val shootSessionName: String = "",
    val shootDurationMin: Int = 60,
    val shootStartDelaySec: Int = 5,
    val shootDitherEvery: Int = 0, // 0 disables dithering
)

class SettingsRepo(private val context: Context) {
    companion object {
        val FOCAL = floatPreferencesKey("focal")
        val SENSOR = stringPreferencesKey("sensor")
        val OVERLAP = floatPreferencesKey("overlap")
        val MIN_HOURS = floatPreferencesKey("min_hours")
        val MIN_PEAK_ALT = floatPreferencesKey("min_peak_alt")
        val MOON_SEP = floatPreferencesKey("moon_sep")
        val MAG_LIMIT = floatPreferencesKey("mag_limit")
        val TOP = intPreferencesKey("top")
        val SORT_BY_SCORE = booleanPreferencesKey("sort_by_score")
        val GRID_MIN = intPreferencesKey("grid_min")
        val CATALOGS = stringPreferencesKey("catalogs")
        val LINK_SITE = stringPreferencesKey("link_site")
        val SELECTED_SITE = stringPreferencesKey("selected_site")
        val NIGHT_VISION = booleanPreferencesKey("night_vision")
        val INDOOR_THEME = stringPreferencesKey("indoor_theme")
        val SOLAR_SYSTEM = booleanPreferencesKey("solar_system")
        val SHARPLESS = booleanPreferencesKey("sharpless")
        val SHARPLESS_MIN_DIAM = floatPreferencesKey("sharpless_min_diam")
        val COMETS = booleanPreferencesKey("comets")
        val COMET_MAG_LIMIT = floatPreferencesKey("comet_mag_limit")
        val PRESSURE_HPA = floatPreferencesKey("pressure_hpa")
        val TEMP_C = floatPreferencesKey("temp_c")
        val EXPOSURE_CALIBRATED_NS = longPreferencesKey("exposure_calibrated_ns")
        val EXTENDED_EXPOSURE = booleanPreferencesKey("extended_exposure")
        val SHOOT_EXPOSURE_NS = longPreferencesKey("shoot_exposure_ns")
        val SHOOT_ISO = intPreferencesKey("shoot_iso")
        val SHOOT_FOCUS_DIOPTRES = floatPreferencesKey("shoot_focus_dioptres")
        val SHOOT_PREVIEW_GAIN = floatPreferencesKey("shoot_preview_gain")
        val SHOOT_PEAKING = booleanPreferencesKey("shoot_peaking")
        val SHOOT_SESSION_NAME = stringPreferencesKey("shoot_session_name")
        val SHOOT_DURATION_MIN = intPreferencesKey("shoot_duration_min")
        val SHOOT_START_DELAY_SEC = intPreferencesKey("shoot_start_delay_sec")
        val SHOOT_DITHER_EVERY = intPreferencesKey("shoot_dither_every")
    }

    val flow: Flow<AppSettings> = context.dataStore.data.map { p ->
        AppSettings(
            focal = p[FOCAL] ?: 800f,
            sensor = p[SENSOR] ?: "23.5x15.7",
            overlap = p[OVERLAP] ?: 0.15f,
            minHours = p[MIN_HOURS] ?: 1f,
            minPeakAlt = p[MIN_PEAK_ALT] ?: 20f,
            moonSep = p[MOON_SEP] ?: 30f,
            magLimit = p[MAG_LIMIT] ?: 11f,
            top = p[TOP] ?: 30,
            sortByScore = p[SORT_BY_SCORE] ?: true,
            gridMin = p[GRID_MIN] ?: 10,
            catalogs = p[CATALOGS] ?: "M",
            linkSite = p[LINK_SITE] ?: "simbad",
            selectedSite = p[SELECTED_SITE] ?: "",
            nightVision = p[NIGHT_VISION] ?: false,
            indoorTheme = p[INDOOR_THEME] ?: DEFAULT_INDOOR_THEME,
            solarSystem = p[SOLAR_SYSTEM] ?: true,
            sharpless = p[SHARPLESS] ?: true,
            sharplessMinDiam = p[SHARPLESS_MIN_DIAM] ?: 10f,
            comets = p[COMETS] ?: false,
            cometMagLimit = p[COMET_MAG_LIMIT] ?: 12f,
            pressureHpa = p[PRESSURE_HPA] ?: 1010f,
            tempC = p[TEMP_C] ?: 10f,
            exposureCalibratedNs = p[EXPOSURE_CALIBRATED_NS] ?: 0L,
            extendedExposure = p[EXTENDED_EXPOSURE] ?: false,
            shootExposureNs = p[SHOOT_EXPOSURE_NS] ?: 0L,
            shootIso = p[SHOOT_ISO] ?: 0,
            shootFocusDioptres = p[SHOOT_FOCUS_DIOPTRES] ?: 0f,
            shootPreviewGain = p[SHOOT_PREVIEW_GAIN] ?: 4f,
            shootPeaking = p[SHOOT_PEAKING] ?: true,
            shootSessionName = p[SHOOT_SESSION_NAME] ?: "",
            shootDurationMin = p[SHOOT_DURATION_MIN] ?: 60,
            shootStartDelaySec = p[SHOOT_START_DELAY_SEC] ?: 5,
            shootDitherEvery = p[SHOOT_DITHER_EVERY] ?: 0,
        )
    }

    suspend fun <T> set(key: Preferences.Key<T>, value: T) {
        context.dataStore.edit { it[key] = value }
    }
}

class SettingsViewModel(app: Application) : AndroidViewModel(app) {
    private val repo = SettingsRepo(app)
    val settings = repo.flow.stateIn(viewModelScope, SharingStarted.Eagerly, AppSettings())

    fun <T> set(key: Preferences.Key<T>, value: T) {
        viewModelScope.launch { repo.set(key, value) }
    }
}
