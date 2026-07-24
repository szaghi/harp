package org.szaghi.harp

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PyBridge.ensureStarted(this)
        setContent { HarpApp() }
    }
}

/** One bottom-nav destination: its [label] and its core-material [icon]. */
private data class TabItem(val label: String, val icon: ImageVector)

@Composable
fun HarpApp() {
    var tab by remember { mutableIntStateOf(0) }
    // Tab order is deliberate and matches the workflow: Home (the dashboard the
    // app lands on) -> Horizon (set the site) -> Plan (pick targets) -> Align
    // (put the mount on the pole) -> Settings. Only the SELECTED tab shows its
    // label (and takes the leftover width so it never wraps); the rest are
    // icon-only and shrink to their glyph, so the bar stays legible as more
    // tabs are added.
    //
    // Icons are material-icons-CORE (the app avoids the multi-MB -extended
    // artifact), except two hand-built vectors: the compass rose
    // (CompassRoseIcon) and the skyline (HorizonIcon). The latter replaced a
    // map pin, which said "a location" rather than "the profile of what blocks
    // your sky".
    //
    // "Align" covers both of that tab's stages — the sensor compass and the
    // polar-alignment assistant — and is short enough never to clip as the
    // selected label; the fuller names live on the stage switch inside.
    val tabs = listOf(
        TabItem("Home", Icons.Filled.Home),
        TabItem("Horizon", HorizonIcon),
        TabItem("Plan", Icons.AutoMirrored.Filled.List),
        TabItem("Align", CompassRoseIcon),
        TabItem("Settings", Icons.Filled.Settings),
    )
    // Settings are hoisted here so the chosen theme wraps the whole app and
    // the night-vision toggle is reachable from every tab; the same instance
    // is handed to the Settings tab so the picker and toggle stay in sync.
    val settingsVm = viewModel<SettingsViewModel>()
    val settings by settingsVm.settings.collectAsState()
    // One sites store shared by the Plan picker and the Horizon Save button.
    val sitesVm = viewModel<SitesViewModel>()
    LaunchedEffect(Unit) { sitesVm.refresh() }
    // The observation log is hoisted too: the Plan tab shows per-target totals
    // and logs sessions, and Settings offers the export — one instance keeps
    // those views consistent without either re-reading the file behind the other.
    val logVm = viewModel<LogViewModel>()

    HarpAppTheme(nightVision = settings.nightVision, indoorThemeId = settings.indoorTheme) {
        Scaffold { padding ->
            Column(Modifier.padding(padding)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    // Custom tab bar (not Material TabRow, which splits width
                    // equally and squeezes the labelled tab into a wrap): the
                    // selected tab weighs 1f and shows a single-line label; the
                    // icon-only tabs wrap to their glyph.
                    tabs.forEachIndexed { i, item ->
                        HarpTab(
                            item = item,
                            selected = tab == i,
                            onClick = { tab = i },
                            modifier = if (tab == i) Modifier.weight(1f) else Modifier,
                        )
                    }
                    // Global red night-vision toggle — reachable at the scope
                    // without digging into Settings. Text label avoids pulling
                    // in the material-icons-extended artifact.
                    TextButton(onClick = {
                        settingsVm.set(SettingsRepo.NIGHT_VISION, !settings.nightVision)
                    }) {
                        Text(if (settings.nightVision) "● red" else "○ red")
                    }
                }
                when (tab) {
                    0 -> HomeScreen(viewModel<HomeViewModel>()) { tab = it }
                    1 -> HorizonScreen(viewModel<HorizonViewModel>(), sitesVm)
                    2 -> PlanScreen(viewModel<PlanViewModel>(), sitesVm, logVm)
                    3 -> CompassScreen(viewModel<CompassViewModel>())
                    4 -> SettingsScreen(settingsVm, logVm)
                }
            }
        }
    }
}

/**
 * One tab in the custom bar. Selected: icon + single-line label on the
 * primary colour, with an underline; unselected: icon only, muted. The
 * caller gives the selected tab `Modifier.weight(1f)` so its label gets the
 * leftover width and never wraps.
 */
@Composable
private fun HarpTab(
    item: TabItem,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val tint = if (selected) MaterialTheme.colorScheme.primary
    else MaterialTheme.colorScheme.onSurfaceVariant
    Column(
        modifier
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(item.icon, contentDescription = item.label, tint = tint)
            if (selected) {
                Text(
                    item.label,
                    color = tint,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Clip,
                    modifier = Modifier.padding(start = 6.dp),
                )
            }
        }
        // selected-tab underline indicator
        if (selected) {
            Spacer(Modifier.height(4.dp))
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(2.dp)
                    .background(MaterialTheme.colorScheme.primary),
            )
        }
    }
}
