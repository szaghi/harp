package org.szaghi.harp

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** One saved observing site, mirror of harp.sites.SiteEntry. */
data class SiteUi(
    val name: String,
    val label: String,
    val lat: Double,
    val lon: Double,
    val elev: Double,
    val tz: String,
    val hasHrz: Boolean,
    val isDefault: Boolean,
)

/**
 * Durable multi-site store, backed by the shared harp core through
 * `sites_bridge`. The config (`sites.yaml` + one `.hrz` per site) lives under
 * the app's `filesDir` — private, durable storage that survives cache
 * eviction and 'Clear cache', unlike the wizard's old `cacheDir` scratch file.
 *
 * The layout is byte-identical to the CLI's: the whole directory can be
 * copied to a desktop `~/.config/harp/` and used with `harp --site`.
 */
class SitesRepo(private val app: Application) {

    /** filesDir is the config dir shared with the Python bridge. */
    val configDir: String = app.filesDir.absolutePath

    private fun bridge() = PyBridge.py.getModule("sites_bridge")

    /** Absolute path to the selected site's .hrz, or "" if it has none. */
    fun hrzPathFor(name: String): String =
        if (name.isBlank()) "" else bridge().callAttr("hrz_path_for", configDir, name).toString()

    fun list(): Pair<String?, List<SiteUi>> {
        val json = JSONObject(bridge().callAttr("list_sites", configDir).toString())
        if (json.has("error")) return null to emptyList()
        val default = json.optString("default").ifBlank { null }
        val arr = json.getJSONArray("sites")
        val out = buildList {
            for (i in 0 until arr.length()) {
                val s = arr.getJSONObject(i)
                add(
                    SiteUi(
                        name = s.getString("name"),
                        label = s.getString("label"),
                        lat = s.getDouble("lat"),
                        lon = s.getDouble("lon"),
                        elev = s.optDouble("elev", 0.0),
                        tz = s.optString("tz", "UTC"),
                        hasHrz = s.optBoolean("has_hrz", false),
                        isDefault = s.optBoolean("default", false),
                    )
                )
            }
        }
        return default to out
    }

    /** Add/update a site; pass hrz content to also (re)write its horizon. */
    fun save(
        name: String,
        label: String,
        lat: Double,
        lon: Double,
        elev: Double,
        tz: String,
        hrz: String?,
        makeDefault: Boolean,
    ): String {
        val req = JSONObject().apply {
            put("config_dir", configDir)
            put("name", name)
            put("label", label)
            put("lat", lat)
            put("lon", lon)
            put("elev", elev)
            put("tz", tz)
            if (hrz != null) put("hrz", hrz)
            put("make_default", makeDefault)
        }
        val res = JSONObject(bridge().callAttr("save_site", req.toString()).toString())
        return if (res.has("error")) res.getString("error") else ""
    }

    fun remove(name: String): String {
        val res = JSONObject(bridge().callAttr("remove_site", configDir, name).toString())
        return if (res.has("error")) res.getString("error") else ""
    }

    fun setDefault(name: String): String {
        val res = JSONObject(bridge().callAttr("set_default", configDir, name).toString())
        return if (res.has("error")) res.getString("error") else ""
    }
}

/**
 * Holds the saved-site list and drives the store off the main thread. Shared
 * by the Plan screen (site picker) and the Horizon wizard (Save button).
 */
class SitesViewModel(app: Application) : AndroidViewModel(app) {
    private val repo = SitesRepo(app)
    private val settings = SettingsRepo(app)

    val sites = mutableStateListOf<SiteUi>()
    var defaultName by mutableStateOf<String?>(null); private set
    var status by mutableStateOf(""); private set
    var busy by mutableStateOf(false); private set

    /** The persisted selected-site name (empty = fall back to default). */
    val selectedName = settings.flow
        .map { it.selectedSite }
        .stateIn(viewModelScope, SharingStarted.Eagerly, "")

    val configDir: String get() = repo.configDir

    fun refresh() {
        busy = true
        viewModelScope.launch {
            val (def, list) = withContext(Dispatchers.IO) { repo.list() }
            defaultName = def
            sites.clear()
            sites.addAll(list)
            busy = false
        }
    }

    /** Save the wizard's built .hrz into a (new or existing) named site. */
    fun saveWizardHorizon(
        name: String,
        lat: Double,
        lon: Double,
        elev: Double,
        tz: String,
        hrzContent: String,
        makeDefault: Boolean,
        onDone: (ok: Boolean) -> Unit = {},
    ) {
        busy = true
        viewModelScope.launch {
            val err = withContext(Dispatchers.IO) {
                repo.save(name, name, lat, lon, elev, tz, hrzContent, makeDefault)
            }
            status = if (err.isEmpty()) "saved site '$name'" else "save failed: $err"
            refresh()
            onDone(err.isEmpty())
        }
    }

    fun select(name: String) {
        viewModelScope.launch {
            settings.set(SettingsRepo.SELECTED_SITE, name)
            withContext(Dispatchers.IO) { repo.setDefault(name) }
            refresh()
        }
    }

    fun remove(name: String) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { repo.remove(name) }
            refresh()
        }
    }
}
