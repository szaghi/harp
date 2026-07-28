package org.szaghi.harp

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.launch
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.ln

/** Which settings sheet is showing, if any. */
enum class SheetTab { NONE, CAMERA, SESSION }

/**
 * The Shoot tab: a manual astro camera.
 *
 * Viewfinder-first. The preview fills the screen because framing a faint target
 * is the whole job at night, and everything else is chrome drawn over it. The
 * two actions -- one frame, or a whole sequence -- are permanently on screen,
 * because a control you must scroll to find is a control you cannot use in the
 * dark with cold hands.
 *
 * Settings are split by *interaction shape*, not by category. Exposure and ISO
 * are ordered ladders, so they share one detented wheel driven by the chip row.
 * Focus is a hill climb against a live score, so it gets its own mode. The rest
 * are switches and text, so they live in a sheet. Forcing all of them onto one
 * control would misrepresent what they are.
 */
@Composable
fun ShootScreen(vm: ShootViewModel) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()

    var hasCamera by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val askCamera = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { hasCamera = it }

    if (!hasCamera) {
        Column(Modifier.padding(16.dp)) {
            Text("The Shoot tab needs the camera.", style = MaterialTheme.typography.bodyLarge)
            Spacer(Modifier.height(8.dp))
            Button(onClick = { askCamera.launch(Manifest.permission.CAMERA) }) {
                Text("Grant camera access")
            }
        }
        return
    }

    val caps by vm.caps.collectAsState()
    val stats by vm.stats.collectAsState()
    val exposureNs by vm.exposureNs.collectAsState()
    val iso by vm.iso.collectAsState()
    val focusD by vm.focusDioptres.collectAsState()
    val peaking by vm.focusPeaking.collectAsState()
    val channel by vm.channel.collectAsState()
    val focusMode by vm.focusMode.collectAsState()
    val lastShot by vm.lastShot.collectAsState()
    val progress by SequenceService.progress.collectAsState()

    val previewView = remember { PreviewView(context) }
    val controller = remember { CaptureController(context) }
    val analysisExecutor = remember { Executors.newSingleThreadExecutor() }
    var status by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var sheet by remember { mutableStateOf(SheetTab.NONE) }

    // One analyzer for the session: histogram and focus score come from a
    // single pass over the luminance plane.
    val analyzer = remember {
        ImageAnalysis.Analyzer { img ->
            val s = analyseLuma(img)
            img.close()
            vm.onStats(s)
        }
    }

    DisposableEffect(Unit) {
        // The job is cancelled explicitly on dispose: bind() suspends on the
        // provider future, and without this a screen torn down mid-bind would
        // resume afterwards and re-bind the camera to a dead lifecycle owner --
        // with nothing left to unbind it.
        SequenceService.uiVisible = true
        val job = scope.launch {
            try {
                val c = controller.bind(
                    owner = lifecycleOwner,
                    surfaceProvider = previewView.surfaceProvider,
                    analyzerExecutor = analysisExecutor,
                    analyzer = analyzer,
                    wantDng = true,
                )
                vm.onCapabilities(c)
                controller.applySettings(vm.settings(), c)
            } catch (e: Exception) {
                status = "camera bind failed: ${e.message}"
            }
        }
        onDispose {
            job.cancel()
            SequenceService.uiVisible = false
            // Do NOT tear down the camera while a sequence is mid-flight. The
            // service captures through this same controller, and unbinding here
            // would kill its session the moment the user leaves the tab or
            // backgrounds the app -- exactly the situations the foreground
            // service exists to survive. finish() releases it in that case.
            if (!SequenceService.progress.value.running) {
                SequenceService.controllerRef = null
                controller.unbind()
                analysisExecutor.shutdown()
            }
        }
    }

    // Push manual settings whenever they change: the sensor holds the last
    // request until told otherwise.
    LaunchedEffect(exposureNs, iso, focusD, caps) {
        val c = caps ?: return@LaunchedEffect
        runCatching { controller.applySettings(vm.settings(), c) }
            .onFailure { status = "settings rejected: ${it.message}" }
    }

    Column(Modifier.fillMaxSize()) {
        Box(
            Modifier
                .fillMaxWidth()
                .weight(1f),
        ) {
            AndroidView({ previewView }, Modifier.fillMaxSize())

            // Corner overlays: readable without covering the centre of frame,
            // which is where the target being aimed at actually sits.
            CaptureBadge(
                caps,
                progress,
                Modifier
                    .align(Alignment.TopStart)
                    .padding(8.dp),
            )
            if (peaking) {
                Text(
                    String.format(Locale.US, "focus %.1f", stats.focusScore),
                    color = Color(0xFFE8D44D),
                    style = MaterialTheme.typography.labelSmall,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(8.dp),
                )
            }
            HistogramOverlay(
                stats,
                Modifier
                    .align(Alignment.BottomStart)
                    .padding(8.dp)
                    .fillMaxWidth(0.44f)
                    .height(46.dp),
            )

            // Exactly one panel occupies the lower preview at a time.
            when {
                focusMode -> FocusModePanel(
                    vm = vm,
                    caps = caps,
                    focusD = focusD,
                    modifier = Modifier.align(Alignment.BottomCenter),
                )

                sheet != SheetTab.NONE -> SettingsSheet(
                    vm = vm,
                    caps = caps,
                    tab = sheet,
                    onTab = { sheet = it },
                    onClose = { sheet = SheetTab.NONE },
                    exposureNs = exposureNs,
                    modifier = Modifier.align(Alignment.BottomCenter),
                )

                else -> ChipWheelPanel(
                    vm = vm,
                    caps = caps,
                    channel = channel,
                    exposureNs = exposureNs,
                    iso = iso,
                    focusD = focusD,
                    onOpenSheet = { sheet = it },
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            }
        }

        // Pinned actions. Present in every state, so Capture and Start are
        // never more than one tap away.
        ActionBar(
            vm = vm,
            caps = caps,
            controller = controller,
            focusMode = focusMode,
            progress = progress,
            busy = busy,
            onBusy = { busy = it },
            onStatus = { status = it },
        )

        if (status.isNotEmpty() || lastShot != null) {
            Column(Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
                if (status.isNotEmpty()) {
                    Text(status, style = MaterialTheme.typography.bodySmall)
                }
                lastShot?.let { AchievedReadout(it) }
            }
        }
    }
}

/**
 * Live state badge, top-left of the preview.
 *
 * During a sequence this is the only place the frame count appears while the
 * wheel is up, so it takes precedence over the format note.
 */
@Composable
private fun CaptureBadge(
    caps: CameraCapabilities?,
    progress: SequenceProgress,
    modifier: Modifier = Modifier,
) {
    val text = when {
        progress.running -> "RUNNING - frame ${progress.frame}/${progress.total}"
        caps == null -> "starting camera..."
        caps.dngSupported -> "DNG"
        else -> "JPEG - no DNG on this camera"
    }
    Text(
        text,
        color = if (progress.running) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.onSurface
        },
        style = MaterialTheme.typography.labelSmall,
        fontFamily = FontFamily.Monospace,
        modifier = modifier
            .background(Color.Black.copy(alpha = 0.5f), RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

/**
 * The default lower panel: the chip row, and the wheel it drives.
 *
 * The chips are both readout and channel selector. That dual role removes the
 * modal round trip a plain viewfinder layout suffers: switching from exposure
 * to ISO is one tap, not close-then-reopen, which matters because those two are
 * tuned against each other and against the histogram.
 */
@Composable
private fun ChipWheelPanel(
    vm: ShootViewModel,
    caps: CameraCapabilities?,
    channel: WheelChannel,
    exposureNs: Long,
    iso: Int,
    focusD: Float,
    onOpenSheet: (SheetTab) -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = caps ?: return
    Column(
        modifier
            .fillMaxWidth()
            .background(
                Brush.verticalGradient(
                    0f to Color.Transparent,
                    0.35f to Color.Black.copy(alpha = 0.65f),
                    1f to MaterialTheme.colorScheme.background,
                ),
            )
            .padding(top = 22.dp),
    ) {
        when (channel) {
            WheelChannel.EXPOSURE -> {
                val usableMax = vm.usableMaxExposureNs()
                val ladder = remember(c, usableMax) {
                    StopLadder.forExposure(
                        minNs = c.exposureMinNs,
                        advertisedMaxNs = c.exposureMaxNs,
                        usableMaxNs = usableMax,
                    )
                }
                StopWheelWithValue(
                    ladder = ladder,
                    index = ladder.nearestIndex(exposureNs),
                    onIndexChange = { vm.setExposureNs(ladder[it].value) },
                )
            }

            WheelChannel.ISO -> {
                val ladder = remember(c) {
                    StopLadder.forIso(c.isoMin, c.isoMax, c.maxAnalogIso)
                }
                StopWheelWithValue(
                    ladder = ladder,
                    index = ladder.nearestIndex(iso.toLong()),
                    onIndexChange = { vm.setIso(ladder[it].value.toInt()) },
                )
            }

            WheelChannel.NONE -> Unit
        }

        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SettingChip(
                label = StopLadder.formatExposureLabel(exposureNs),
                active = channel == WheelChannel.EXPOSURE,
                enabled = c.manualSensorSupported,
                onClick = { vm.setChannel(WheelChannel.EXPOSURE) },
            )
            SettingChip(
                label = "ISO $iso",
                active = channel == WheelChannel.ISO,
                enabled = c.manualSensorSupported,
                onClick = { vm.setChannel(WheelChannel.ISO) },
            )
            SettingChip(
                label = if (focusD <= 0.001f) "∞" else String.format(Locale.US, "%.2f", focusD),
                active = false,
                enabled = c.manualFocusSupported,
                onClick = { vm.enterFocusMode() },
            )
            SettingChip(
                label = "···",
                active = false,
                enabled = true,
                onClick = { onOpenSheet(SheetTab.CAMERA) },
            )
        }

        if (!c.manualSensorSupported) {
            Text(
                "This device does not guarantee manual exposure; requested values " +
                    "may be ignored.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 2.dp),
            )
        }
    }
}

/** One chip: a readout when idle, filled when it owns the wheel. */
@Composable
private fun SettingChip(
    label: String,
    active: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val bg = if (active) scheme.primary else Color.Transparent
    val fg = when {
        !enabled -> scheme.onSurfaceVariant.copy(alpha = 0.4f)
        active -> scheme.onPrimary
        else -> scheme.onSurface
    }
    Text(
        label,
        style = MaterialTheme.typography.labelMedium,
        fontFamily = FontFamily.Monospace,
        fontWeight = if (active) FontWeight.Bold else FontWeight.Normal,
        color = fg,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(bg)
            .then(if (enabled) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 11.dp, vertical = 6.dp),
    )
}

/**
 * Focus mode: the whole lower screen given over to one hill climb.
 *
 * Focus is not a value to be set but a maximum to be found, and the number that
 * identifies it is already computed on every preview frame. Showing its recent
 * history turns a blind search into a legible one: you can see which way the
 * score is moving and, when it turns over, that you have just passed the peak.
 */
@Composable
private fun FocusModePanel(
    vm: ShootViewModel,
    caps: CameraCapabilities?,
    focusD: Float,
    modifier: Modifier = Modifier,
) {
    val c = caps ?: return
    val trace by vm.focusTrace.collectAsState()
    val maxD = c.minFocusDistanceDioptres ?: 0f

    Column(
        modifier
            .fillMaxWidth()
            .background(
                Brush.verticalGradient(
                    0f to Color.Transparent,
                    0.3f to Color.Black.copy(alpha = 0.7f),
                    1f to MaterialTheme.colorScheme.background,
                ),
            )
            .padding(start = 12.dp, end = 12.dp, top = 24.dp, bottom = 8.dp),
    ) {
        FocusTrace(
            trace = trace,
            peakIndex = vm.focusPeakIndex(),
            modifier = Modifier
                .fillMaxWidth()
                .height(40.dp),
        )

        Spacer(Modifier.height(6.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            Slider(
                value = ShootViewModel.dioptresToSlider(focusD, maxD),
                onValueChange = {
                    vm.setFocusDioptres(ShootViewModel.sliderToDioptres(it, maxD))
                },
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            OutlinedButton(onClick = { vm.focusInfinity() }) { Text("∞") }
        }

        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                "near",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                if (trace.isEmpty()) {
                    "turn slowly - watch the trace"
                } else {
                    String.format(Locale.US, "best %.1f", trace.maxOrNull() ?: 0f)
                },
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.primary,
            )
            Text(
                "∞",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** The focus-score history, with the running best marked. */
@Composable
private fun FocusTrace(
    trace: List<Float>,
    peakIndex: Int,
    modifier: Modifier = Modifier,
) {
    val accent = MaterialTheme.colorScheme.primary
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Canvas(modifier) {
        if (trace.isEmpty()) return@Canvas
        // Scale to the window's own range, not to zero: focus scores sit on a
        // large pedestal, and an absolute scale would flatten the very
        // variation the user is trying to read.
        val lo = trace.min()
        val hi = trace.max()
        val span = (hi - lo).takeIf { it > 1e-6f } ?: 1f
        val w = size.width / trace.size
        for (i in trace.indices) {
            val norm = (trace[i] - lo) / span
            val h = (0.12f + norm * 0.88f) * size.height
            drawRect(
                color = if (i == peakIndex) accent else muted.copy(alpha = 0.55f),
                topLeft = Offset(i * w, size.height - h),
                size = Size(w * 0.82f, h),
            )
        }
    }
}

/**
 * The settings sheet: everything that is neither a ladder nor a hill climb.
 *
 * Two named groups that never interleave -- the separation a single scrolling
 * column of mixed camera and sequence controls could not provide.
 */
@Composable
private fun SettingsSheet(
    vm: ShootViewModel,
    caps: CameraCapabilities?,
    tab: SheetTab,
    onTab: (SheetTab) -> Unit,
    onClose: () -> Unit,
    exposureNs: Long,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(topStart = 14.dp, topEnd = 14.dp))
            .background(MaterialTheme.colorScheme.background)
            .padding(bottom = 6.dp),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(start = 12.dp, end = 12.dp, top = 8.dp, bottom = 6.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                SettingChip("Camera", tab == SheetTab.CAMERA, true) { onTab(SheetTab.CAMERA) }
                SettingChip("Session", tab == SheetTab.SESSION, true) { onTab(SheetTab.SESSION) }
            }
            Text(
                "Done",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.clickable(onClick = onClose),
            )
        }

        Column(
            Modifier
                .heightIn(max = 300.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            when (tab) {
                SheetTab.SESSION -> SessionSheet(vm, caps, exposureNs)
                else -> CameraSheet(vm, caps)
            }
        }
    }
}

/** Camera group: the advisor, then the settings that are not ladders. */
@Composable
private fun CameraSheet(vm: ShootViewModel, caps: CameraCapabilities?) {
    val gain by vm.previewGain.collectAsState()
    val peaking by vm.focusPeaking.collectAsState()
    val calib by vm.calibration.collectAsState()
    val advice by vm.adviceState.collectAsState()

    // Ask when the sheet first shows the card, and again if the camera probe
    // lands later. Keyed on capabilities rather than fired blindly, because the
    // advisor needs the sensor's limits to say anything useful -- and not
    // re-fired on every recomposition, since it crosses into Python and reads
    // the site store.
    LaunchedEffect(caps) {
        if (caps != null && vm.adviceState.value == AdviceState.Idle) {
            vm.requestAdvice()
        }
    }

    AdvisorCard(vm, advice)

    SheetRow(
        label = "Preview gain",
        note = "display only - never touches the saved frame",
    ) {
        Slider(
            value = (gain - 1f) / 15f,
            onValueChange = { vm.setPreviewGain(1f + it * 15f) },
            modifier = Modifier.width(120.dp),
        )
    }

    SheetRow(label = "Focus peaking") {
        Switch(checked = peaking, onCheckedChange = { vm.toggleFocusPeaking() })
    }

    caps?.let { c ->
        SheetRow(label = "Sensor", note = c.summary()) {}
        if (!c.dngSupported) {
            SheetNote(
                "No DNG on this camera - frames will be JPEG, which stacks poorly.",
                error = true,
            )
        }
    }

    when (val cal = calib) {
        is CalibrationState.Running -> SheetNote(
            String.format(Locale.US, "Calibrating exposure: trying %.0f s...", cal.stepSec),
        )

        is CalibrationState.Done -> SheetNote(
            if (cal.calibration.extended) {
                "Extended exposure verified: " +
                    ShootViewModel.formatExposure(cal.calibration.measuredMaxNs) +
                    " (advertised " +
                    ShootViewModel.formatExposure(cal.calibration.advertisedMaxNs) + ")"
            } else {
                "No usable extension; staying at " +
                    ShootViewModel.formatExposure(cal.calibration.advertisedMaxNs)
            },
        )

        is CalibrationState.Failed -> SheetNote("Calibration failed: ${cal.reason}", error = true)

        CalibrationState.Idle -> Unit
    }
}

/**
 * The advisor card.
 *
 * Shows the reasoning, not only the numbers. `advise()` returns a list of plain
 * sentences explaining every choice, and that list is the point: a user who
 * knows *why* a value is right can adapt when the sky changes, where one merely
 * handed settings cannot.
 *
 * When the site declares no Bortle class or SQM, the exposure advice still
 * holds but ISO does not -- the card says so and names the fix rather than
 * inventing a number, which is the same neutrality rule harp.sky follows.
 */
@Composable
private fun AdvisorCard(vm: ShootViewModel, state: AdviceState) {
    val scheme = MaterialTheme.colorScheme
    Column(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp)
            .clip(RoundedCornerShape(9.dp))
            .background(scheme.primary.copy(alpha = 0.08f))
            .padding(10.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "HARP ADVISES",
                style = MaterialTheme.typography.labelSmall,
                fontWeight = FontWeight.Bold,
                color = scheme.primary,
            )
            when (state) {
                is AdviceState.Ready -> Row(
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // Recompute: the advice is a snapshot, and session length
                    // feeds it. Offered rather than invalidated automatically,
                    // because the call reads the site store and crosses into
                    // Python -- not something to run on every slider tick.
                    Text(
                        "Refresh",
                        style = MaterialTheme.typography.labelLarge,
                        color = scheme.onSurfaceVariant,
                        modifier = Modifier.clickable { vm.requestAdvice() },
                    )
                    Text(
                        "Apply",
                        style = MaterialTheme.typography.labelLarge,
                        color = scheme.primary,
                        modifier = Modifier.clickable { vm.applyAdvice(state.advice) },
                    )
                }

                AdviceState.Running -> Text(
                    "working...",
                    style = MaterialTheme.typography.labelSmall,
                    color = scheme.onSurfaceVariant,
                )

                is AdviceState.Failed -> Text(
                    "Retry",
                    style = MaterialTheme.typography.labelLarge,
                    color = scheme.primary,
                    modifier = Modifier.clickable { vm.requestAdvice() },
                )

                else -> Unit
            }
        }

        when (state) {
            is AdviceState.Ready -> {
                val a = state.advice
                Text(
                    buildString {
                        append(String.format(Locale.US, "%.1f s", a.exposureS))
                        append(" · ISO ")
                        append(a.iso?.toString() ?: "—")
                        append(" · ")
                        append(a.frames)
                        append(" frames")
                    },
                    style = MaterialTheme.typography.titleSmall,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                )
                a.reasons.forEach {
                    Text(
                        "· $it",
                        style = MaterialTheme.typography.labelSmall,
                        color = scheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }
                if (a.needsSkyQuality) {
                    // Name the destination rather than only the problem: the
                    // field lives on the saved site in the Horizon tab, and
                    // "set a Bortle class" is useless if you cannot find where.
                    Text(
                        "No sky quality for this site, so ISO cannot be advised. " +
                            "Set a Bortle class or SQM when saving the site in the " +
                            "Horizon tab, then refresh.",
                        style = MaterialTheme.typography.labelSmall,
                        color = scheme.error,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }

            is AdviceState.Failed -> Text(
                state.reason,
                style = MaterialTheme.typography.labelSmall,
                color = scheme.error,
            )

            else -> Text(
                "Waiting for the camera probe...",
                style = MaterialTheme.typography.labelSmall,
                color = scheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * Session group: name, length, and the pre-flight verdict.
 *
 * The estimate sits with the settings that determine it, so lengthening the
 * session and watching the storage cost rise is one glance rather than two
 * screens.
 */
@Composable
private fun SessionSheet(
    vm: ShootViewModel,
    caps: CameraCapabilities?,
    exposureNs: Long,
) {
    val context = LocalContext.current
    val name by vm.sessionName.collectAsState()
    val durationMin by vm.durationMin.collectAsState()
    val startDelaySec by vm.startDelaySec.collectAsState()
    val ditherEvery by vm.ditherEvery.collectAsState()

    val plan = rememberSequencePlan(vm, caps, exposureNs)

    OutlinedTextField(
        value = name,
        onValueChange = { vm.setSessionName(it) },
        label = { Text("Sequence name") },
        placeholder = { Text("session") },
        singleLine = true,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp),
    )

    LadderRow(
        label = "Duration",
        ladder = StopLadder.forDurationMinutes(),
        value = durationMin.toLong(),
    ) { vm.setDurationMin(it.toInt()) }

    LadderRow(
        label = "Start delay",
        note = "settles shutter shake before frame 1",
        ladder = StopLadder.forStartDelaySeconds(),
        value = startDelaySec.toLong(),
    ) { vm.setStartDelaySec(it.toInt()) }

    LadderRow(
        label = "Dither every",
        note = "pause for a manual nudge",
        ladder = StopLadder.forDitherEvery(),
        value = ditherEvery.toLong(),
    ) { vm.setDitherEvery(it.toInt()) }

    Text(
        "${plan.frames} frames · " +
            SequencePlan.formatDuration(plan.integrationMs) + " light · " +
            SequencePlan.formatBytes(plan.estimatedBytes()) + " · runs " +
            SequencePlan.formatDuration(plan.totalMs),
        style = MaterialTheme.typography.labelSmall,
        fontFamily = FontFamily.Monospace,
        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
    )

    // All three are Binder round-trips, so they are cached rather than run on
    // every recomposition -- this panel recomposes once per captured frame
    // while a sequence is live.
    val free = remember(plan.frames) { freeBytes(context) }
    val battery = remember(plan.frames) { batteryPercent(context) }
    val thermal = remember(plan.frames) { thermalStatus(context) }
    preflight(plan, free, battery, thermal).forEach {
        Text(
            it.message,
            style = MaterialTheme.typography.labelSmall,
            color = if (it.isBlocking()) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 1.dp),
        )
    }
}

/** A sheet row whose value is chosen from a ladder on the shared wheel. */
@Composable
private fun LadderRow(
    label: String,
    ladder: StopLadder,
    value: Long,
    note: String? = null,
    onPick: (Long) -> Unit,
) {
    var open by remember { mutableStateOf(false) }
    val index = ladder.nearestIndex(value)
    Column {
        SheetRow(label = label, note = note) {
            Text(
                ladder[index].label,
                style = MaterialTheme.typography.labelLarge,
                fontFamily = FontFamily.Monospace,
                color = if (open) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
                modifier = Modifier
                    .clickable { open = !open }
                    .padding(horizontal = 6.dp, vertical = 2.dp),
            )
        }
        if (open) {
            StopWheel(
                ladder = ladder,
                index = index,
                onIndexChange = { onPick(ladder[it].value) },
                height = 84.dp,
            )
        }
    }
}

/** Label, optional explanation, and a trailing control. */
@Composable
private fun SheetRow(
    label: String,
    note: String? = null,
    trailing: @Composable () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyMedium)
            note?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        trailing()
    }
}

@Composable
private fun SheetNote(text: String, error: Boolean = false) {
    Text(
        text,
        style = MaterialTheme.typography.labelSmall,
        color = if (error) {
            MaterialTheme.colorScheme.error
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        },
        modifier = Modifier.padding(horizontal = 12.dp, vertical = 2.dp),
    )
}

/**
 * Capture and Start, pinned below the preview in every state.
 *
 * During a sequence Start becomes Stop in place and Capture demotes to an
 * outline: the stopping action must be unmistakable at 2 a.m., and nothing else
 * may move, so muscle memory survives the transition.
 */
@Composable
private fun ActionBar(
    vm: ShootViewModel,
    caps: CameraCapabilities?,
    controller: CaptureController,
    focusMode: Boolean,
    progress: SequenceProgress,
    busy: Boolean,
    onBusy: (Boolean) -> Unit,
    onStatus: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val exposureNs by vm.exposureNs.collectAsState()
    val plan = rememberSequencePlan(vm, caps, exposureNs)

    Column(Modifier.fillMaxWidth()) {
        if (progress.running) {
            LinearProgressIndicator(
                progress = { progress.fraction },
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                "frame ${progress.frame} of ${progress.total} · " +
                    SequencePlan.formatDuration(progress.etaMs) + " remaining",
                style = MaterialTheme.typography.labelSmall,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 2.dp),
            )
        }

        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedButton(
                onClick = {
                    val c = caps
                    if (c != null) {
                        onBusy(true)
                        onStatus("capturing...")
                        scope.launch {
                            val ext = if (c.dngSupported) ".dng" else ".jpg"
                            val fileName = "harp_${System.currentTimeMillis()}$ext"
                            val out = controller.captureFrame(
                                relativeDir = "DCIM/HARP",
                                fileName = fileName,
                                settings = vm.settings(),
                                dng = c.dngSupported,
                            )
                            vm.onShot(out)
                            onStatus(
                                when {
                                    !out.ok -> "failed: ${out.error}"
                                    !out.exposureHonoured ->
                                        "SAVED, but the sensor gave " +
                                            ShootViewModel.formatExposure(
                                                out.achievedExposureNs,
                                            ) +
                                            ", not " +
                                            ShootViewModel.formatExposure(
                                                out.requestedExposureNs,
                                            )

                                    else -> "saved $fileName"
                                },
                            )
                            onBusy(false)
                        }
                    }
                },
                enabled = !busy && caps != null,
                modifier = Modifier.weight(1f),
            ) {
                Text(
                    when {
                        busy -> "..."
                        focusMode -> "Test frame"
                        else -> "Capture"
                    },
                )
            }

            when {
                focusMode -> Button(
                    onClick = { vm.exitFocusMode() },
                    modifier = Modifier.weight(1f),
                ) { Text("Done") }

                progress.running -> Button(
                    onClick = { SequenceService.stop(context) },
                    modifier = Modifier.weight(1f),
                ) { Text("Stop") }

                else -> {
                    val free = remember(plan.frames) { freeBytes(context) }
                    val battery = remember(plan.frames) { batteryPercent(context) }
                    val thermal = remember(plan.frames) { thermalStatus(context) }
                    val blocked = preflight(plan, free, battery, thermal).any { it.isBlocking() }
                    Button(
                        onClick = {
                            // The service reuses the already-bound camera rather
                            // than opening a second session, which would fight
                            // this one.
                            SequenceService.controllerRef = controller
                            SequenceService.start(context, plan)
                        },
                        enabled = caps != null && !blocked,
                        modifier = Modifier.weight(1f),
                    ) {
                        Text("Start · " + SequencePlan.formatDuration(plan.totalMs))
                    }
                }
            }
        }
    }
}

/**
 * Build the sequence plan from current settings.
 *
 * The interval is derived rather than offered: it must hold the exposure plus
 * the file write, and letting the user set it independently would only create a
 * way to be wrong.
 */
@Composable
private fun rememberSequencePlan(
    vm: ShootViewModel,
    caps: CameraCapabilities?,
    exposureNs: Long,
): SequencePlan {
    val name by vm.sessionName.collectAsState()
    val iso by vm.iso.collectAsState()
    val focusD by vm.focusDioptres.collectAsState()
    val durationMin by vm.durationMin.collectAsState()
    val startDelaySec by vm.startDelaySec.collectAsState()
    val ditherEvery by vm.ditherEvery.collectAsState()

    val intervalMs = SequencePlan.minIntervalMs(exposureNs)
    val frames = SequencePlan.framesForDuration(durationMin * 60_000L, intervalMs)
    return SequencePlan(
        name = name.ifBlank { "session" },
        exposureNs = exposureNs,
        iso = iso,
        focusDioptres = focusD,
        frames = frames,
        intervalMs = intervalMs,
        startDelayMs = startDelaySec * 1000L,
        ditherEvery = ditherEvery,
        dng = caps?.dngSupported ?: false,
    )
}

/**
 * What the sensor actually delivered on the last frame.
 *
 * Shown always, not only on mismatch: a requested exposure is a request, and
 * seeing the achieved one is how the user learns whether to trust the extension.
 */
@Composable
private fun AchievedReadout(o: CaptureOutcome) {
    Text(
        "Last frame: requested " +
            ShootViewModel.formatExposure(o.requestedExposureNs) +
            ", achieved " +
            ShootViewModel.formatExposure(o.achievedExposureNs) +
            " at ISO ${o.achievedIso}",
        style = MaterialTheme.typography.labelSmall,
        fontFamily = FontFamily.Monospace,
        color = if (o.exposureHonoured) {
            MaterialTheme.colorScheme.onSurfaceVariant
        } else {
            MaterialTheme.colorScheme.error
        },
    )
}

/** Log-scaled luminance histogram; log-y because the sky dominates every bin. */
@Composable
private fun HistogramOverlay(stats: PreviewStats, modifier: Modifier = Modifier) {
    val error = MaterialTheme.colorScheme.error
    val ink = MaterialTheme.colorScheme.onSurface
    Canvas(modifier) {
        val n = stats.bins.size
        if (n == 0) return@Canvas
        val maxV = (stats.bins.maxOrNull() ?: 1).coerceAtLeast(1)
        val w = size.width / n
        for (i in 0 until n) {
            // Log scale: a linear histogram of a night sky is one spike at the
            // left and nothing visible anywhere else.
            val h = (ln(1.0 + stats.bins[i]) / ln(1.0 + maxV)).toFloat() * size.height
            drawRect(
                color = if (i >= n - 1 && stats.clipping) error else ink,
                topLeft = Offset(i * w, size.height - h),
                size = Size(w, h),
            )
        }
    }
}

/** Free space on the volume the frames are written to. */
private fun freeBytes(context: Context): Long = runCatching {
    val dir = context.getExternalFilesDir(null) ?: return@runCatching 0L
    android.os.StatFs(dir.absolutePath).availableBytes
}.getOrDefault(0L)

/** Battery charge, percent, or -1 when unknown. */
private fun batteryPercent(context: Context): Int = runCatching {
    context.getSystemService(android.os.BatteryManager::class.java)
        ?.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
}.getOrDefault(-1)

/**
 * A thermal warning, or null when the device is comfortable.
 *
 * Sustained long-exposure capture heats the sensor, and dark current rises with
 * it -- so a hot phone quietly degrades every remaining frame.
 */
private fun thermalStatus(context: Context): String? = runCatching {
    if (android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.Q) return@runCatching null
    val pm = context.getSystemService(android.os.PowerManager::class.java)
        ?: return@runCatching null
    when (pm.currentThermalStatus) {
        android.os.PowerManager.THERMAL_STATUS_SEVERE -> "severe - frames will be noisier"
        android.os.PowerManager.THERMAL_STATUS_CRITICAL -> "critical - consider pausing"
        android.os.PowerManager.THERMAL_STATUS_EMERGENCY -> "emergency - stop"
        else -> null
    }
}.getOrNull()

/**
 * Histogram and focus score from one pass over the luminance plane.
 *
 * Subsamples on a stride: at preview resolution a full walk every frame costs
 * more than it is worth, and the statistics are indistinguishable.
 */
private fun analyseLuma(img: ImageProxy): PreviewStats {
    val plane = img.planes[0]
    val buf = plane.buffer
    val stride = plane.rowStride
    val w = img.width
    val h = img.height
    val bins = IntArray(PreviewStats.BIN_COUNT)
    var gradSum = 0.0
    var gradN = 0
    val step = 4

    var row = 0
    while (row < h - step) {
        val base = row * stride
        var col = 0
        while (col < w - step) {
            val v = buf.get(base + col).toInt() and 0xFF
            bins[v * PreviewStats.BIN_COUNT / 256]++
            // Horizontal gradient only: cheap, and a star is isotropic enough
            // that one axis ranks focus as well as two.
            val right = buf.get(base + col + step).toInt() and 0xFF
            gradSum += abs(v - right)
            gradN++
            col += step
        }
        row += step
    }

    var peak = 0
    var modeBin = 0
    var modeCount = 0
    for (i in bins.indices) {
        if (bins[i] > 0) peak = i
        if (bins[i] > modeCount) {
            modeCount = bins[i]
            modeBin = i
        }
    }
    return PreviewStats(
        bins = bins,
        peakBin = peak,
        backgroundBin = modeBin,
        focusScore = if (gradN > 0) (gradSum / gradN).toFloat() else 0f,
    )
}
