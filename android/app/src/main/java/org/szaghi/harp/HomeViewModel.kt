package org.szaghi.harp

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.TimeZone

/**
 * Tonight's headline numbers for the Home dashboard: the darkness window and
 * the Moon. Null until the bridge answers; the dashboard renders dashes rather
 * than blocking, because Home must open instantly.
 */
data class TonightUi(
    val darkStart: String,
    val darkEnd: String,
    val darkHours: Double,
    val moonIllum: Double,
    val moonUp: String,
) {
    /** "6h 12m" — the Sun's headline figure. */
    val darkLabel: String
        get() {
            val h = darkHours.toInt()
            val m = ((darkHours - h) * 60).toInt()
            return "${h}h ${m.toString().padStart(2, '0')}m"
        }

    val moonLabel: String get() = "moon ${(moonIllum * 100).toInt()}%"
}

/**
 * Backing model for the Home dashboard.
 *
 * Sources its position the same way the Plan tab does — the default saved site
 * if there is one, else the last GPS fix — so Home agrees with the rest of the
 * app rather than inventing its own notion of "where we are".
 */
class HomeViewModel(app: Application) : AndroidViewModel(app) {

    var tonight by mutableStateOf<TonightUi?>(null); private set
    var siteLabel by mutableStateOf(""); private set
    var loading by mutableStateOf(false); private set
    var error by mutableStateOf(""); private set

    private val sitesRepo = SitesRepo(app)

    private fun lastKnownLocation(): Triple<Double, Double, Double>? {
        val ctx = getApplication<Application>()
        val granted =
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED ||
                ContextCompat.checkSelfPermission(
                    ctx, Manifest.permission.ACCESS_COARSE_LOCATION,
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

    /** Recompute tonight. Cheap (no catalogue), so it is safe on every resume. */
    fun refresh() {
        if (loading) return
        loading = true
        viewModelScope.launch {
            val (label, raw) = withContext(Dispatchers.IO) {
                try {
                    val (_, sites) = sitesRepo.list()
                    val site = sites.firstOrNull { it.isDefault } ?: sites.firstOrNull()
                    val req = JSONObject()
                    if (site != null) {
                        req.put("lat", site.lat)
                        req.put("lon", site.lon)
                        req.put("elev", site.elev)
                        req.put("tz", site.tz)
                    } else {
                        val fix = lastKnownLocation()
                            ?: return@withContext null to "no saved site and no GPS fix yet"
                        req.put("lat", fix.first)
                        req.put("lon", fix.second)
                        req.put("elev", fix.third)
                        req.put("tz", TimeZone.getDefault().id)
                    }
                    val out = PyBridge.py.getModule("home_bridge")
                        .callAttr("tonight", req.toString()).toString()
                    (site?.label ?: "current position") to out
                } catch (e: Exception) {
                    null to "${e.javaClass.simpleName}: ${e.message}"
                }
            }
            loading = false
            if (label == null) {
                error = raw
                tonight = null
                return@launch
            }
            siteLabel = label
            try {
                val o = JSONObject(raw)
                if (o.has("error")) {
                    error = o.getString("error")
                    tonight = null
                } else {
                    error = ""
                    tonight = TonightUi(
                        darkStart = o.getString("dark_start"),
                        darkEnd = o.getString("dark_end"),
                        darkHours = o.getDouble("dark_hours"),
                        moonIllum = o.getDouble("moon_illum"),
                        moonUp = o.getString("moon_up"),
                    )
                }
            } catch (e: Exception) {
                error = "bad payload: ${e.message}"
                tonight = null
            }
        }
    }
}
