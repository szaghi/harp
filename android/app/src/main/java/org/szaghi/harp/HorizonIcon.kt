package org.szaghi.harp

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathBuilder
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

/**
 * A skyline icon for the Horizon tab.
 *
 * Replaces the stock map pin, which said "a location" — the wrong idea. This
 * tab is about an OBSTRUCTION PROFILE: where the skyline cuts off the sky and
 * at what altitude sky begins. So the glyph is a ground line, an irregular
 * roofline with a tree notch, and the sky dome dashed above it.
 *
 * Stroked rather than filled, matching the Material outline weight at 24dp.
 * The dome is drawn at half alpha and is the first thing to fade at bottom-tab
 * size (15-16dp) — deliberately, since the roofline silhouette is what carries
 * the meaning when small.
 */
val HorizonIcon: ImageVector by lazy {
    fun PathBuilder.polyline(vararg pts: Pair<Float, Float>) {
        moveTo(pts[0].first, pts[0].second)
        for (i in 1 until pts.size) lineTo(pts[i].first, pts[i].second)
    }

    ImageVector.Builder(
        name = "Horizon",
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).apply {
        // ground line
        path(
            stroke = SolidColor(Color.Black), // recoloured by Icon tint
            strokeLineWidth = 1.7f,
            strokeLineCap = StrokeCap.Round,
            strokeLineJoin = StrokeJoin.Round,
        ) {
            moveTo(2f, 20f)
            lineTo(22f, 20f)
        }
        // the profile itself: two roof steps, a tree notch, a taller block
        path(
            stroke = SolidColor(Color.Black),
            strokeLineWidth = 1.7f,
            strokeLineCap = StrokeCap.Round,
            strokeLineJoin = StrokeJoin.Round,
        ) {
            polyline(
                4f to 20f, 4f to 15f, 7f to 13f, 9f to 16f,
                12f to 9f, 15f to 14f, 17f to 13f, 20f to 17f, 20f to 20f,
            )
        }
        // sky dome, dimmed — the first element to drop out at small sizes
        path(
            stroke = SolidColor(Color.Black),
            strokeAlpha = 0.5f,
            strokeLineWidth = 1.7f,
            strokeLineCap = StrokeCap.Round,
        ) {
            moveTo(5f, 7f)
            arcTo(
                horizontalEllipseRadius = 9f,
                verticalEllipseRadius = 9f,
                theta = 0f,
                isMoreThanHalf = false,
                isPositiveArc = true,
                x1 = 19f,
                y1 = 7f,
            )
        }
    }.build()
}
