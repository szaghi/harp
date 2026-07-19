package org.szaghi.harp

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

/**
 * Phase-3 planner: the CLI's `harp plan` on the phone — GPS site, the
 * wizard's captured horizon, ranked by the same desirability score.
 * Tap a target to open its info link (SIMBAD) in the browser.
 */
@Composable
fun PlanScreen(vm: PlanViewModel) {
    val context = LocalContext.current

    Column(Modifier.fillMaxSize().padding(16.dp)) {
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

        LazyColumn(Modifier.weight(1f)) {
            items(vm.rows) { r ->
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
