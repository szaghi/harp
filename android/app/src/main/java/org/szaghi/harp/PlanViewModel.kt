package org.szaghi.harp

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.util.TimeZone

data class PlanRowUi(
    val name: String,
    val score: Double,
    val hours: Double,
    val window: String,
    val moon: String,
    val frame: String,
    val link: String,
)

/** Runs the shared harp planner on-device and holds the ranked result. */
class PlanViewModel(app: Application) : AndroidViewModel(app) {

    var running by mutableStateOf(false); private set
    var summary by mutableStateOf(""); private set
    var error by mutableStateOf(""); private set
    val rows = mutableStateListOf<PlanRowUi>()

    // per-run input; everything else lives in Settings (DataStore)
    var date by mutableStateOf("")
    private val settingsRepo = SettingsRepo(app)

    private fun lastKnownLocation(): Triple<Double, Double, Double>? {
        val ctx = getApplication<Application>()
        val granted =
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED ||
                ContextCompat.checkSelfPermission(
                    ctx, Manifest.permission.ACCESS_COARSE_LOCATION
                ) == PackageManager.PERMISSION_GRANTED
        if (!granted) return null
        val lm = ctx.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val loc = try {
            lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
        } catch (_: SecurityException) {
            null
        } ?: return null
        return Triple(loc.latitude, loc.longitude, if (loc.hasAltitude()) loc.altitude else 0.0)
    }

    /** The wizard's last exported horizon, if any: capture then plan through it. */
    private fun wizardHorizonPath(): String {
        val f = File(getApplication<Application>().cacheDir, "exports/horizon.hrz")
        return if (f.exists()) f.absolutePath else ""
    }

    fun runPlan() {
        val loc = lastKnownLocation()
        if (loc == null) {
            error = "no location fix - grant location and get a GPS fix in the wizard tab"
            return
        }
        running = true
        error = ""
        rows.clear()
        viewModelScope.launch {
            val s = settingsRepo.flow.first()
            summary = "planning (${s.catalogs})..."
            val result = withContext(Dispatchers.IO) {
                val request = JSONObject().apply {
                    put("lat", loc.first)
                    put("lon", loc.second)
                    put("elev", loc.third)
                    put("tz", TimeZone.getDefault().id)
                    put("date", date.trim())
                    put("hrz_path", wizardHorizonPath())
                    put("focal_mm", s.focal.toDouble())
                    put("sensor", s.sensor)
                    put("overlap", s.overlap.toDouble())
                    put("min_hours", s.minHours.toDouble())
                    put("min_peak_alt", s.minPeakAlt.toDouble())
                    put("moon_sep", s.moonSep.toDouble())
                    put("mag_limit", s.magLimit.toDouble())
                    put("top", s.top)
                    put("sort", if (s.sortByScore) "score" else "hours")
                    put("grid_min", s.gridMin)
                    put("catalogs", s.catalogs)
                    put("link_site", s.linkSite)
                }
                try {
                    PyBridge.py.getModule("planner_bridge")
                        .callAttr("run_plan", request.toString()).toString()
                } catch (e: Exception) {
                    """{"error": "${e.message}"}"""
                }
            }
            val parsed = runCatching { JSONObject(result) }.getOrNull()
            if (parsed == null || parsed.has("error")) {
                error = parsed?.optString("error") ?: "planner returned unparsable output"
                summary = ""
            } else {
                val night = parsed.getJSONObject("night")
                val moon = parsed.getJSONObject("moon")
                val hhmm = { iso: String -> iso.substringAfter('T').take(5) }
                summary =
                    "${night.getString("date")}  darkness ${hhmm(night.getString("dusk"))}" +
                        "-${hhmm(night.getString("dawn"))}  Moon " +
                        "${(moon.getDouble("illumination") * 100).toInt()}%  |  " +
                        "${parsed.getString("horizon")}  |  " +
                        "${parsed.optInt("n_targets")} targets in " +
                        "${parsed.optDouble("elapsed_s")} s"
                val arr = parsed.getJSONArray("rows")
                for (i in 0 until arr.length()) {
                    val r = arr.getJSONObject(i)
                    rows.add(
                        PlanRowUi(
                            name = r.getString("name"),
                            score = r.getDouble("score"),
                            hours = r.getDouble("hours"),
                            window = r.getString("window"),
                            moon = r.getString("moon"),
                            frame = r.getString("frame"),
                            link = r.getString("link"),
                        )
                    )
                }
            }
            running = false
        }
    }
}
