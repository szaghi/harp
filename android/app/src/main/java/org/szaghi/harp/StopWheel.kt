package org.szaghi.harp

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

/** Horizontal travel, in pixels, that advances the wheel by one stop. */
private const val DRAG_PER_STOP = 42f

/** Radians spanned by the visible arc. */
private const val ARC_SPREAD = 0.92f

private const val GUIDE_SEGMENTS = 48

/**
 * An arc of detented stops, dragged horizontally under the thumb.
 *
 * The arc is not decoration. Ticks radiate from a virtual centre well below the
 * screen, so each falls at the same distance from the base of the thumb -- the
 * path a thumb sweeps while the hand holding the phone stays still. A flat
 * slider forces a stretch or a regrip at its ends, which at night, gloved, on a
 * control that sets exposure, is a real cost.
 *
 * Selection is discrete by construction: no continuous value hides behind the
 * wheel, only [StopLadder] indices. Drag distance accumulates until it crosses
 * [DRAG_PER_STOP], then commits one stop and keeps the remainder, so a slow
 * sweep steps predictably rather than skidding.
 *
 * @param ladder the stops to offer
 * @param index currently selected index into [ladder]
 * @param onIndexChange fired once per detent crossed
 */
@Composable
fun StopWheel(
    ladder: StopLadder,
    index: Int,
    onIndexChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
    height: Dp = 116.dp,
) {
    val scheme = MaterialTheme.colorScheme
    val measurer = rememberTextMeasurer()

    // Carried across drag events so a slow sweep accumulates toward the next
    // detent instead of being rounded away on every frame.
    val residue = remember(ladder) { mutableFloatStateOf(0f) }

    Box(
        modifier
            .fillMaxWidth()
            .height(height)
            .pointerInput(ladder, index) {
                detectHorizontalDragGestures(
                    onDragEnd = { residue.floatValue = 0f },
                    onDragCancel = { residue.floatValue = 0f },
                ) { change, dragAmount ->
                    change.consume()
                    residue.floatValue += dragAmount
                    if (abs(residue.floatValue) >= DRAG_PER_STOP) {
                        // Dragging right reveals lower stops, as on a physical
                        // dial whose near edge travels with the thumb.
                        val dir = if (residue.floatValue > 0f) -1 else 1
                        residue.floatValue -= dir * -DRAG_PER_STOP
                        val next = (index + dir).coerceIn(0, ladder.size - 1)
                        if (next != index) onIndexChange(next)
                    }
                }
            },
    ) {
        Canvas(
            Modifier
                .fillMaxWidth()
                .height(height),
        ) {
            drawWheel(
                ladder = ladder,
                index = index,
                measurer = measurer,
                tickColor = scheme.onSurface,
                mutedColor = scheme.onSurfaceVariant,
                accentColor = scheme.primary,
                gatedColor = scheme.error,
            )
        }
    }
}

private fun DrawScope.drawWheel(
    ladder: StopLadder,
    index: Int,
    measurer: TextMeasurer,
    tickColor: Color,
    mutedColor: Color,
    accentColor: Color,
    gatedColor: Color,
) {
    if (ladder.size == 0) return

    // The centre sits below the canvas: the shallower the arc, the closer it
    // matches a thumb's sweep rather than a wrist rotation.
    val cx = size.width / 2f
    val cy = size.height + size.height * 0.78f
    val radius = cy - size.height * 0.20f

    val per = ARC_SPREAD / (ladder.size - 1).coerceAtLeast(1)
    val centreAngle = -PI.toFloat() / 2f
    val startAngle = centreAngle - index * per

    // Guide arc: faint, and mostly there so the wheel reads as one object
    // rather than a scatter of unrelated ticks.
    for (i in 0 until GUIDE_SEGMENTS) {
        val a0 = -PI.toFloat() + i * (PI.toFloat() / GUIDE_SEGMENTS)
        val a1 = a0 + PI.toFloat() / GUIDE_SEGMENTS * 0.92f
        drawLine(
            color = mutedColor.copy(alpha = 0.22f),
            start = Offset(cx + cos(a0) * radius, cy + sin(a0) * radius),
            end = Offset(cx + cos(a1) * radius, cy + sin(a1) * radius),
            strokeWidth = 1f,
        )
    }

    for (i in ladder.stops.indices) {
        val stop = ladder.stops[i]
        val a = startAngle + i * per
        // Cull ticks that have rotated off the visible half of the arc.
        if (a < -PI.toFloat() || a > 0f) continue

        val selected = i == index
        val tickLen = if (stop.major) size.height * 0.13f else size.height * 0.07f
        val outer = Offset(cx + cos(a) * radius, cy + sin(a) * radius)
        val inner = Offset(
            cx + cos(a) * (radius - tickLen),
            cy + sin(a) * (radius - tickLen),
        )

        val color = when {
            selected -> accentColor
            stop.calibrationGated -> gatedColor
            else -> tickColor
        }
        val alpha = when {
            selected -> 1f
            stop.major -> 0.72f
            else -> 0.38f
        }

        drawLine(
            color = color.copy(alpha = alpha),
            start = outer,
            end = inner,
            strokeWidth = if (selected) 3f else 1.5f,
        )

        // Labels only on whole stops, and never on the selected one -- its
        // value is already spelled out above the wheel.
        if (stop.major && !selected) {
            val lx = cx + cos(a) * (radius - tickLen - size.height * 0.13f)
            val ly = cy + sin(a) * (radius - tickLen - size.height * 0.13f)
            val layout = measurer.measure(
                stop.label,
                TextStyle(
                    fontSize = 9.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Medium,
                    color = if (stop.calibrationGated) gatedColor else mutedColor,
                ),
            )
            // Rotate each label normal to the arc, as on a dial face.
            rotate(
                degrees = (a * 180f / PI.toFloat()) + 90f,
                pivot = Offset(lx, ly),
            ) {
                drawText(
                    layout,
                    topLeft = Offset(
                        lx - layout.size.width / 2f,
                        ly - layout.size.height / 2f,
                    ),
                )
            }
        }
    }
}

/**
 * The wheel plus its value readout and, when relevant, its provenance note.
 *
 * Kept separate from [StopWheel] so the wheel stays a pure control: the caller
 * decides what the value means and how loudly to say so.
 */
@Composable
fun StopWheelWithValue(
    ladder: StopLadder,
    index: Int,
    onIndexChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val stop = ladder[index]
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            stop.label,
            style = MaterialTheme.typography.titleMedium,
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.Bold,
            color = if (stop.calibrationGated) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.primary
            },
        )
        if (stop.calibrationGated) {
            // Say why this stop exists. It lies past what the sensor advertises
            // and rests on a measurement the user opted into and can revoke --
            // silence would present it as an ordinary setting.
            Text(
                "past the advertised limit - verified by calibration",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = 1.dp),
            )
        }
        StopWheel(
            ladder = ladder,
            index = index,
            onIndexChange = onIndexChange,
            modifier = Modifier.padding(top = 2.dp),
        )
    }
}
