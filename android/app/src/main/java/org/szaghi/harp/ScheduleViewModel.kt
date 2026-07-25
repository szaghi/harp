package org.szaghi.harp

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** One candidate night for a target, as ranked by the shared core. */
data class NightUi(
    val date: String,
    val score: Double,
    val contHours: Double,
    val window: String,
    val moonIllum: Double,
    val moonSep: Double,
    val usable: Boolean,
) {
    /** "14%" — the Moon is usually why one night beats another. */
    val moonLabel: String get() = "${(moonIllum * 100).toInt()}%"
}

/**
 * "When should I shoot this target?" — the inverse of the Plan tab's question.
 *
 * Backed by `schedule_bridge` over the shared `harp.schedule` core, so the app
 * ranks nights exactly as `harp when` does: same desirability score, same
 * tie-breaks, no second definition of "good".
 *
 * THIS IS THE APP'S MOST EXPENSIVE CALL. It plans one night per day in the
 * window, and Chaquopy is several times slower than desktop CPython — a
 * fortnight measured at 1.5 s on a laptop is plausibly ~10 s on a phone. Hence:
 * it never runs implicitly (only when the user taps), it defaults to 14 nights
 * rather than the CLI's 30, and [running] exists so the UI can show progress
 * instead of appearing frozen.
 */
class ScheduleViewModel(app: Application) : AndroidViewModel(app) {

    val nights = mutableStateListOf<NightUi>()

    var target by mutableStateOf(""); private set
    var days by mutableStateOf(DEFAULT_DAYS); private set
    var running by mutableStateOf(false); private set
    var error by mutableStateOf(""); private set

    /** False when the target never clears the horizon in the whole window. */
    var anyUsable by mutableStateOf(true); private set

    private val settingsRepo = SettingsRepo(app)
    private val sitesRepo = SitesRepo(app)

    private fun bridge() = PyBridge.py.getModule("schedule_bridge")

    /** Clear the sheet's state; called when it is dismissed. */
    fun reset() {
        nights.clear()
        target = ""
        days = DEFAULT_DAYS
        error = ""
        anyUsable = true
    }

    /**
     * Rank the coming [days] nights for [targetName].
     *
     * Resolves the site and rig the same way the Plan tab does — the default
     * saved site — so the schedule answers for the place the plan was computed
     * for, not some other notion of "here".
     */
    fun run(targetName: String, days: Int = this.days) {
        if (running) return
        running = true
        target = targetName
        this.days = days
        error = ""
        viewModelScope.launch {
            val raw = withContext(Dispatchers.IO) {
                try {
                    val s = settingsRepo.flow.first()
                    val (_, sites) = sitesRepo.list()
                    val site = sites.firstOrNull { it.isDefault } ?: sites.firstOrNull()
                    if (site == null) {
                        return@withContext JSONObject()
                            .put("error", "no saved site — add one in the Horizon tab")
                            .toString()
                    }
                    val req = JSONObject().apply {
                        put("target", targetName)
                        put("days", days)
                        put("top", TOP_SHOWN)
                        put("focal_mm", s.focal.toDouble())
                        put("sensor", s.sensor)
                        put("catalogs", s.catalogs)
                        put("lat", site.lat)
                        put("lon", site.lon)
                        put("elev", site.elev)
                        put("tz", site.tz)
                        put("label", site.label)
                        // Sky quality, so `when` ranks with the same contrast
                        // term the Plan tab and CLI use.
                        site.bortle?.let { put("bortle", it) }
                        site.sqm?.let { put("sqm", it) }
                        val hrz = sitesRepo.hrzPathFor(site.name)
                        if (hrz.isNotBlank()) put("hrz_path", hrz)
                    }
                    bridge().callAttr("run_when", req.toString()).toString()
                } catch (e: Exception) {
                    JSONObject().put("error", "${e.javaClass.simpleName}: ${e.message}").toString()
                }
            }
            running = false
            try {
                val o = JSONObject(raw)
                if (o.has("error")) {
                    error = o.getString("error")
                    nights.clear()
                    return@launch
                }
                anyUsable = o.optBoolean("any_usable", true)
                val arr = o.getJSONArray("nights")
                nights.clear()
                for (i in 0 until arr.length()) {
                    val n = arr.getJSONObject(i)
                    nights.add(
                        NightUi(
                            date = n.getString("date"),
                            score = n.getDouble("score"),
                            contHours = n.getDouble("cont_hours"),
                            window = n.getString("window"),
                            moonIllum = n.getDouble("moon_illum"),
                            moonSep = n.getDouble("moon_sep"),
                            usable = n.optBoolean("usable", true),
                        )
                    )
                }
            } catch (e: Exception) {
                error = "bad schedule payload: ${e.message}"
                nights.clear()
            }
        }
    }

    companion object {
        /** Half the CLI's 30: a phone is slower, and a fortnight is the usual question. */
        const val DEFAULT_DAYS = 14

        /** Longer windows the user can opt into once they have seen the cost. */
        val DAY_CHOICES = listOf(7, 14, 30)

        /** Nights listed. More than this is a wall of dates on a phone screen. */
        const val TOP_SHOWN = 6
    }
}
