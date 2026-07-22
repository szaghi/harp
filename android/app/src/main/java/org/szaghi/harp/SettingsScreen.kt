package org.szaghi.harp

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.datastore.preferences.core.Preferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Settings + About: the on-device mirror of the CLI configuration surface. */
@Composable
fun SettingsScreen(vm: SettingsViewModel) {
    val s by vm.settings.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var versions by remember { mutableStateOf("") }

    Column(
        Modifier
            .padding(16.dp)
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
    ) {
        Section("Appearance")
        Label("night vision (red) — for use at the telescope")
        ChipRow(
            listOf(
                "indoor" to !s.nightVision,
                "red night vision" to s.nightVision,
            ),
        ) { vm.set(SettingsRepo.NIGHT_VISION, it == "red night vision") }
        Label("indoor dark theme")
        ThemeChips(selected = s.indoorTheme) { vm.set(SettingsRepo.INDOOR_THEME, it) }
        Text(
            "the red theme always overrides the indoor pick while it is on",
            style = MaterialTheme.typography.bodySmall,
        )

        Section("Rig")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumField("focal mm", s.focal, Modifier.weight(1f)) { vm.set(SettingsRepo.FOCAL, it) }
            TextField2("sensor WxH mm", s.sensor, Modifier.weight(1f)) {
                vm.set(SettingsRepo.SENSOR, it)
            }
        }
        NumField("mosaic overlap (0-0.5)", s.overlap, Modifier.fillMaxWidth()) {
            if (it in 0f..0.5f) vm.set(SettingsRepo.OVERLAP, it)
        }

        Section("Planning")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumField("min hours", s.minHours, Modifier.weight(1f)) {
                vm.set(SettingsRepo.MIN_HOURS, it)
            }
            NumField("min peak alt", s.minPeakAlt, Modifier.weight(1f)) {
                vm.set(SettingsRepo.MIN_PEAK_ALT, it)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumField("Moon sep deg", s.moonSep, Modifier.weight(1f)) {
                vm.set(SettingsRepo.MOON_SEP, it)
            }
            NumField("mag limit", s.magLimit, Modifier.weight(1f)) {
                vm.set(SettingsRepo.MAG_LIMIT, it)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            IntField("rows shown", s.top, Modifier.weight(1f)) { vm.set(SettingsRepo.TOP, it) }
            IntField("grid min", s.gridMin, Modifier.weight(1f)) {
                if (it in 1..60) vm.set(SettingsRepo.GRID_MIN, it)
            }
        }
        Label("ranking")
        ChipRow(
            listOf("score" to s.sortByScore, "hours" to !s.sortByScore),
        ) { vm.set(SettingsRepo.SORT_BY_SCORE, it == "score") }

        Section("Catalogs")
        ChipRow(
            listOf(
                "M" to (s.catalogs == "M"),
                "M+NGC" to (s.catalogs == "M,NGC"),
                "M+NGC+IC" to (s.catalogs == "M,NGC,IC"),
            ),
        ) {
            vm.set(
                SettingsRepo.CATALOGS,
                when (it) {
                    "M+NGC" -> "M,NGC"
                    "M+NGC+IC" -> "M,NGC,IC"
                    else -> "M"
                },
            )
        }
        Text(
            "curated large nebulae are always included; mag limit applies to catalog objects",
            style = MaterialTheme.typography.bodySmall,
        )
        Label("Solar System (Moon + planets)")
        ChipRow(
            listOf(
                "included" to s.solarSystem,
                "off" to !s.solarSystem,
            ),
        ) { vm.set(SettingsRepo.SOLAR_SYSTEM, it == "included") }

        Section("Target links (tap on a plan row)")
        ChipRow(
            listOf("simbad", "wikipedia", "astrobin", "aladin").map { it to (s.linkSite == it) },
        ) { vm.set(SettingsRepo.LINK_SITE, it) }
        Text(
            "wikipedia may 404 on faint objects; aladin always works (sky viewer)",
            style = MaterialTheme.typography.bodySmall,
        )

        Section("About")
        Text(
            "HARP — Horizon-Aware Recommender and Planner\n" +
                "app ${appVersion(context)} | FOSS, GPL/BSD-2/BSD-3/MIT quad license",
            style = MaterialTheme.typography.bodySmall,
        )
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = {
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/szaghi/harp"))
                )
            }) { Text("GitHub") }
            OutlinedButton(onClick = {
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse("https://szaghi.github.io/harp/"))
                )
            }) { Text("Docs") }
            OutlinedButton(onClick = {
                versions = "checking..."
                scope.launch {
                    versions = withContext(Dispatchers.IO) {
                        try {
                            PyBridge.py.getModule("spike").callAttr("stack_versions").toString()
                        } catch (e: Exception) {
                            "diagnostics failed: ${e.message}"
                        }
                    }
                }
            }) { Text("Diagnostics") }
        }
        if (versions.isNotEmpty()) {
            Spacer(Modifier.height(4.dp))
            Text(versions, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(24.dp))
    }
}

private fun appVersion(context: android.content.Context): String = try {
    context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "?"
} catch (_: Exception) {
    "?"
}

@Composable
private fun Section(title: String) {
    Spacer(Modifier.height(12.dp))
    Text(title, style = MaterialTheme.typography.titleMedium)
    HorizontalDivider()
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun Label(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun ChipRow(options: List<Pair<String, Boolean>>, onSelect: (String) -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { (label, selected) ->
            FilterChip(selected = selected, onClick = { onSelect(label) }, label = { Text(label) })
        }
    }
}

/** Wrapping picker over all indoor themes; emits the selected theme id. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ThemeChips(selected: String, onSelect: (String) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        INDOOR_THEMES.forEach { theme ->
            FilterChip(
                selected = theme.id == selected,
                onClick = { onSelect(theme.id) },
                label = { Text(theme.label) },
            )
        }
    }
}

/** Numeric field that persists on every valid parse; keeps invalid text local. */
@Composable
private fun NumField(
    label: String,
    value: Float,
    modifier: Modifier = Modifier,
    onValid: (Float) -> Unit,
) {
    var text by remember(value) { mutableStateOf(if (value % 1f == 0f) "${value.toInt()}" else "$value") }
    OutlinedTextField(
        value = text,
        onValueChange = { t ->
            text = t
            t.replace(',', '.').toFloatOrNull()?.let(onValid)
        },
        label = { Text(label) },
        singleLine = true,
        modifier = modifier,
    )
}

@Composable
private fun IntField(
    label: String,
    value: Int,
    modifier: Modifier = Modifier,
    onValid: (Int) -> Unit,
) {
    var text by remember(value) { mutableStateOf("$value") }
    OutlinedTextField(
        value = text,
        onValueChange = { t ->
            text = t
            t.toIntOrNull()?.let(onValid)
        },
        label = { Text(label) },
        singleLine = true,
        modifier = modifier,
    )
}

@Composable
private fun TextField2(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    onChange: (String) -> Unit,
) {
    var text by remember(value) { mutableStateOf(value) }
    OutlinedTextField(
        value = text,
        onValueChange = { t ->
            text = t
            if (t.isNotBlank()) onChange(t.trim())
        },
        label = { Text(label) },
        singleLine = true,
        modifier = modifier,
    )
}
