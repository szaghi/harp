package org.szaghi.harp

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

/**
 * Phase-3 planner: the CLI's `harp plan` on the phone — GPS site, the
 * wizard's captured horizon, ranked by the same desirability score.
 * Tap a target to open its info link (SIMBAD) in the browser.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PlanScreen(vm: PlanViewModel, sitesVm: SitesViewModel) {
    val context = LocalContext.current
    val selected by sitesVm.selectedName.collectAsState()

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        // Site picker: which saved observatory to plan for. The selection is
        // persisted; an empty store falls through to a live GPS fix.
        if (sitesVm.sites.isEmpty()) {
            Text(
                "No saved site — planning uses your current GPS location. " +
                    "Build and Save a horizon in the Horizon tab to pin an observatory.",
                style = MaterialTheme.typography.bodySmall,
            )
        } else {
            Text("Observing site", style = MaterialTheme.typography.labelMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                sitesVm.sites.forEach { site ->
                    val active = site.name == selected ||
                        (selected.isEmpty() && site.isDefault)
                    FilterChip(
                        selected = active,
                        onClick = { sitesVm.select(site.name) },
                        label = { Text(site.label + if (site.hasHrz) "" else " (flat)") },
                    )
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = vm.date,
            onValueChange = { vm.date = it },
            label = { Text("date YYYY-MM-DD (empty = tonight)") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )
        Spacer(Modifier.height(8.dp))
        Button(
            onClick = { vm.runPlan() },
            enabled = !vm.running,
            modifier = Modifier.fillMaxWidth().height(52.dp),
        ) { Text(if (vm.running) "Planning..." else "Plan tonight") }
        Spacer(Modifier.height(8.dp))

        if (vm.error.isNotEmpty()) {
            Text(vm.error, color = MaterialTheme.colorScheme.error)
        }
        if (vm.summary.isNotEmpty()) {
            Text(vm.summary, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(4.dp))
        }

        // client-side filters: instant re-filtering, no re-planning
        var emissionMode by remember { mutableStateOf(0) } // 0 all, 1 emission, 2 non
        val classFilter = remember { mutableStateListOf<String>() }
        if (vm.rows.isNotEmpty()) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = emissionMode == 1,
                    onClick = { emissionMode = if (emissionMode == 1) 0 else 1 },
                    label = { Text("emission") },
                )
                FilterChip(
                    selected = emissionMode == 2,
                    onClick = { emissionMode = if (emissionMode == 2) 0 else 2 },
                    label = { Text("non-em") },
                )
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                // Nature classes, matching the CLI --filter taxonomy. 'planet'
                // and 'moon' cover the Solar System bodies; 'planetary' stays
                // the (distinct) planetary-nebula class.
                listOf("nebula", "galaxy", "cluster", "planetary", "planet", "moon").forEach { c ->
                    FilterChip(
                        selected = c in classFilter,
                        onClick = {
                            if (c in classFilter) classFilter.remove(c) else classFilter.add(c)
                        },
                        label = { Text(c) },
                    )
                }
            }
            Spacer(Modifier.height(4.dp))
        }
        val shown = vm.rows.filter { r ->
            (classFilter.isEmpty() || r.kindClass in classFilter) &&
                when (emissionMode) {
                    1 -> r.narrowband
                    2 -> !r.narrowband
                    else -> true
                }
        }

        LazyColumn(Modifier.weight(1f)) {
            items(shown) { r ->
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clickable {
                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(r.link)))
                        }
                        .padding(vertical = 6.dp)
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            r.name,
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            "${r.score.toInt()}",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                    Text(
                        "${r.hours} h  |  ${r.window}  |  Moon ${r.moon}  |  ${r.frame}",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                HorizontalDivider()
            }
        }
    }
}
