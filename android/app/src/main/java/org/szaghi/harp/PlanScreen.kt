package org.szaghi.harp

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

/**
 * Phase-3 planner: the CLI's `harp plan` on the phone — GPS site, the
 * wizard's captured horizon, ranked by the same desirability score.
 * Tap a target to open its info link (SIMBAD) in the browser.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PlanScreen(vm: PlanViewModel, sitesVm: SitesViewModel, logVm: LogViewModel) {
    // Which target the log dialog is open for; null = closed.
    var logTarget by rememberSaveable { mutableStateOf<String?>(null) }
    // Totals are read once per entry to the tab: the log only changes when the
    // user logs something, and addSession refreshes them itself.
    LaunchedEffect(Unit) { logVm.refresh() }

    logTarget?.let { target ->
        LogSessionDialog(
            target = target,
            logVm = logVm,
            onDismiss = { logTarget = null },
        )
    }

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
        // Filter the FULL ranked list first, THEN cap to the display limit —
        // so a class filter reaches every ranked target, not a pre-truncated
        // top-N (which on a moonlit night is all narrowband nebulae).
        val filtered = vm.rows.filter { r ->
            (classFilter.isEmpty() || r.kindClass in classFilter) &&
                when (emissionMode) {
                    1 -> r.narrowband
                    2 -> !r.narrowband
                    else -> true
                }
        }
        val shown = filtered.take(vm.displayTop)

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
                        // Integration already logged on this target. Shown for
                        // information only — it never touches the score, since
                        // "already shot" is not "done" and demoting a target
                        // the user may want to revisit is their call, not ours.
                        logVm.totalFor(r.name)?.let { t ->
                            Text(
                                "▣ ${t.integration}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(end = 8.dp),
                            )
                        }
                        Text(
                            "${r.score.toInt()}",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.primary,
                        )
                        TextButton(onClick = { logTarget = r.name }) { Text("log") }
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

/**
 * Record one imaging session on [target].
 *
 * Only subs, exposure and filter are asked for: those three are what make the
 * entry answer "how much data do I have", and anything more is friction at the
 * end of a cold night. Notes are there for the one thing worth remembering.
 * The date defaults to today and is editable, because a session logged the
 * morning after belongs to the night before.
 */
@Composable
private fun LogSessionDialog(
    target: String,
    logVm: LogViewModel,
    onDismiss: () -> Unit,
) {
    var date by rememberSaveable(target) { mutableStateOf(todayIso()) }
    var subs by rememberSaveable(target) { mutableStateOf("") }
    var exposure by rememberSaveable(target) { mutableStateOf("") }
    var filter by rememberSaveable(target) { mutableStateOf("") }
    var notes by rememberSaveable(target) { mutableStateOf("") }

    val existing = logVm.totalFor(target)
    val context = LocalContext.current

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Log $target") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (existing != null) {
                    Text(
                        "already ${existing.integration} over ${existing.sessions} session(s)",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                OutlinedTextField(
                    value = date,
                    onValueChange = { date = it },
                    label = { Text("date (YYYY-MM-DD)") },
                    singleLine = true,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = subs,
                        onValueChange = { subs = it.filter { c -> c.isDigit() } },
                        label = { Text("subs") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = exposure,
                        onValueChange = { exposure = it.filter { c -> c.isDigit() || c == '.' } },
                        label = { Text("exposure (s)") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f),
                    )
                }
                OutlinedTextField(
                    value = filter,
                    onValueChange = { filter = it },
                    label = { Text("filter") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = notes,
                    onValueChange = { notes = it },
                    label = { Text("notes") },
                )
            }
        },
        confirmButton = {
            Button(
                enabled = !logVm.busy,
                onClick = {
                    logVm.addSession(
                        target = target,
                        date = date.ifBlank { todayIso() },
                        subs = subs.toIntOrNull(),
                        exposureS = exposure.toDoubleOrNull(),
                        filter = filter,
                        site = "",
                        rig = "",
                        notes = notes,
                    ) { msg ->
                        Toast.makeText(context, msg, Toast.LENGTH_LONG).show()
                    }
                    onDismiss()
                },
            ) { Text("Save") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

/** Today as YYYY-MM-DD, the log's date format. */
private fun todayIso(): String =
    java.time.LocalDate.now().toString()
