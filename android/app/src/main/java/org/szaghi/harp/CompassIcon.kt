package org.szaghi.harp

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * A compass-rose icon for the Compass tab.
 *
 * The core material-icons set (the app avoids the multi-MB -extended
 * artifact) has no compass glyph, so this is a hand-built [ImageVector]: an
 * 8-point star rose in a 24x24 box, tinted at draw time by the caller's
 * `Icon` colour so it follows the theme (red in night mode). No dependency,
 * no raster asset.
 *
 * The star is generated, not hand-plotted: 8 kite-shaped points around the
 * centre, alternating a long cardinal reach and a shorter intercardinal one,
 * each with two shoulders on an inner ring. Building it from trig keeps the
 * geometry exact and symmetric rather than relying on eyeballed path data.
 */
val CompassRoseIcon: ImageVector by lazy {
    val cx = 12f
    val cy = 12f
    val rLong = 10f // cardinal tip radius
    val rShort = 6.5f // intercardinal tip radius
    val rInner = 2.6f // shoulder ring

    // point angle a (deg, 0 = up/N, clockwise); shoulders at a +/- 45 deg on rInner
    fun x(rad: Double, r: Float) = (cx + r * sin(rad)).toFloat()
    fun y(rad: Double, r: Float) = (cy - r * cos(rad)).toFloat()

    ImageVector.Builder(
        name = "CompassRose",
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).apply {
        path(fill = SolidColor(Color.Black)) { // recoloured by Icon tint
            for (k in 0 until 8) {
                val tip = k * 45.0 * PI / 180.0
                val left = (k * 45.0 - 45.0) * PI / 180.0
                val right = (k * 45.0 + 45.0) * PI / 180.0
                val tipR = if (k % 2 == 0) rLong else rShort
                moveTo(x(tip, tipR), y(tip, tipR))
                lineTo(x(right, rInner), y(right, rInner))
                lineTo(x(tip, 0f), y(tip, 0f)) // hub
                lineTo(x(left, rInner), y(left, rInner))
                close()
            }
        }
    }.build()
}
