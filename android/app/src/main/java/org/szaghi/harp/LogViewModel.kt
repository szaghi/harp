package org.szaghi.harp

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** One target's accumulated integration, as shown on a plan row. */
data class LoggedTotal(val sessions: Int, val integration: String)

/**
 * The observation log: what was actually imaged, and how much of it.
 *
 * Backed by `log_bridge` over the shared `harp.log` core, so the app and the
 * `harp log` CLI read and write the same `observations.yaml` — the file lives
 * beside `sites.yaml` in `filesDir` and can be copied to a desktop
 * `~/.config/harp/` unchanged.
 *
 * This is the ONLY view model in the app that owns data the user cannot
 * regenerate. A plan is recomputed in seconds; an observing history is gone if
 * lost. Two consequences shape the design: every write goes straight through
 * the core's own save (no caching a dirty in-memory copy that a process death
 * would discard), and [exportText] exists so the log can always leave the app.
 *
 * Totals are DISPLAY ONLY. They never feed the ranking — "already shot" is not
 * the same as "done", and quietly demoting a target the user might want to
 * revisit would be the planner making a judgement that belongs to the user.
 */
class LogViewModel(app: Application) : AndroidViewModel(app) {

    /** Integration per target, keyed by the core's normalisation (see [key]). */
    val totals = mutableStateMapOf<String, LoggedTotal>()

    var busy by mutableStateOf(false); private set
    var status by mutableStateOf(""); private set
    var error by mutableStateOf(""); private set

    private val configDir: String = app.filesDir.absolutePath

    private fun bridge() = PyBridge.py.getModule("log_bridge")

    /**
     * Normalise a target name the way the core does — casefold, strip spaces —
     * so "M 42" and "M42" hit the same bucket. The bridge keys its map this
     * way; a lookup that skipped this would silently miss every logged target
     * whose spelling differs from the catalogue's.
     */
    private fun key(target: String): String = target.replace(" ", "").lowercase()

    fun totalFor(target: String): LoggedTotal? = totals[key(target)]

    /** Load every target's totals in one pass. Cheap: one file read, no ephemeris. */
    fun refresh() {
        viewModelScope.launch {
            val raw = withContext(Dispatchers.IO) {
                try {
                    bridge().callAttr("totals_map", configDir).toString()
                } catch (e: Exception) {
                    JSONObject().put("error", "${e.javaClass.simpleName}: ${e.message}").toString()
                }
            }
            try {
                val o = JSONObject(raw)
                if (o.has("error")) {
                    error = o.getString("error")
                    return@launch
                }
                error = ""
                val map = o.getJSONObject("totals")
                totals.clear()
                for (k in map.keys()) {
                    val t = map.getJSONObject(k)
                    totals[k] = LoggedTotal(
                        sessions = t.getInt("sessions"),
                        integration = t.getString("integration"),
                    )
                }
            } catch (e: Exception) {
                error = "bad log payload: ${e.message}"
            }
        }
    }

    /**
     * Record one session and refresh the totals.
     *
     * [onDone] receives a human-readable confirmation carrying the new total,
     * so the UI can state a checkable fact ("M42: now 8h 20m") rather than a
     * bare "saved" the user has to take on trust.
     */
    fun addSession(
        target: String,
        date: String,
        subs: Int?,
        exposureS: Double?,
        filter: String,
        site: String,
        rig: String,
        notes: String,
        onDone: (String) -> Unit = {},
    ) {
        if (busy) return
        busy = true
        viewModelScope.launch {
            val raw = withContext(Dispatchers.IO) {
                try {
                    val req = JSONObject().apply {
                        put("target", target)
                        put("date", date)
                        if (subs != null) put("subs", subs)
                        if (exposureS != null) put("exposure_s", exposureS)
                        if (filter.isNotBlank()) put("filter", filter)
                        if (site.isNotBlank()) put("site", site)
                        if (rig.isNotBlank()) put("rig", rig)
                        if (notes.isNotBlank()) put("notes", notes)
                    }
                    bridge().callAttr("add_entry", configDir, req.toString()).toString()
                } catch (e: Exception) {
                    JSONObject().put("error", "${e.javaClass.simpleName}: ${e.message}").toString()
                }
            }
            busy = false
            try {
                val o = JSONObject(raw)
                if (o.has("error")) {
                    error = o.getString("error")
                    onDone("could not log: ${o.getString("error")}")
                    return@launch
                }
                error = ""
                val total = o.getString("integration")
                val sessions = o.getInt("sessions")
                status = "$target: $total over $sessions session(s)"
                onDone("Logged ${o.getString("logged")} — $target now $total")
                refresh()
            } catch (e: Exception) {
                error = "bad log payload: ${e.message}"
                onDone("could not log: ${e.message}")
            }
        }
    }

    /**
     * The raw `observations.yaml` text, for the share sheet.
     *
     * Returns the file's own bytes rather than a re-serialisation, so what the
     * user shares is exactly what the CLI would read back. Yields null when
     * there is nothing to share, so the caller can say so instead of exporting
     * an empty file.
     */
    fun exportText(onReady: (String?) -> Unit) {
        viewModelScope.launch {
            val raw = withContext(Dispatchers.IO) {
                try {
                    bridge().callAttr("export_text", configDir).toString()
                } catch (e: Exception) {
                    JSONObject().put("error", "${e.javaClass.simpleName}: ${e.message}").toString()
                }
            }
            try {
                val o = JSONObject(raw)
                if (o.has("error") || o.optBoolean("empty", false)) {
                    onReady(null)
                    return@launch
                }
                onReady(o.getString("text"))
            } catch (_: Exception) {
                onReady(null)
            }
        }
    }
}
