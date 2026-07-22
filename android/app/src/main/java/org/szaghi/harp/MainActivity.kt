package org.szaghi.harp

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
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
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PyBridge.ensureStarted(this)
        setContent { HarpApp() }
    }
}

@Composable
fun HarpApp() {
    var tab by remember { mutableIntStateOf(0) }
    val titles = listOf("Plan", "Horizon", "Settings")
    // Settings are hoisted here so the chosen theme wraps the whole app and
    // the night-vision toggle is reachable from every tab; the same instance
    // is handed to the Settings tab so the picker and toggle stay in sync.
    val settingsVm = viewModel<SettingsViewModel>()
    val settings by settingsVm.settings.collectAsState()
    // One sites store shared by the Plan picker and the Horizon Save button.
    val sitesVm = viewModel<SitesViewModel>()
    LaunchedEffect(Unit) { sitesVm.refresh() }

    HarpAppTheme(nightVision = settings.nightVision, indoorThemeId = settings.indoorTheme) {
        Scaffold { padding ->
            Column(Modifier.padding(padding)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TabRow(selectedTabIndex = tab, modifier = Modifier.weight(1f)) {
                        titles.forEachIndexed { i, title ->
                            Tab(
                                selected = tab == i,
                                onClick = { tab = i },
                                text = { Text(title) },
                            )
                        }
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
                    0 -> PlanScreen(viewModel<PlanViewModel>(), sitesVm)
                    1 -> HorizonScreen(viewModel<HorizonViewModel>(), sitesVm)
                    2 -> SettingsScreen(settingsVm)
                }
            }
        }
    }
}
