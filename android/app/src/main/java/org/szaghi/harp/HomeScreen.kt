package org.szaghi.harp

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.ClipOp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.TextUnitType
import androidx.compose.ui.unit.dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Settings

/**
 * The Home dashboard: a mini solar system.
 *
 * A cropped Sun sits off the left edge — only its lit crescent shows, an ember
 * rather than a noon disc so it never outshines the interface and, in red
 * night-vision mode, never spoils dark adaptation. Tonight's headline numbers
 * are placed on the Sun's SHADOWED side, the only part of a crescent where
 * text has contrast.
 *
 * The right two-thirds hold the operational tabs as planets on faint
 * elliptical paths, ordered outward as the actual workflow: set the site ->
 * plan the night -> align the mount -> configure.
 *
 * Construction: the Sun and the orbit ellipses are a [Canvas] (they are pure
 * geometry), but every planet is a real composable with an [Icon] and [Text].
 * That keeps labels scalable, translatable and reachable by a screen reader,
 * and gives each planet an honest touch target — none of which a
 * canvas-drawn dashboard would have.
 *
 * The composition is authored in a 160x320 design space and scaled uniformly,
 * so it is identical on every screen. Planets are laid out for FOUR tabs;
 * adding a fifth means re-spacing [PLANETS], not appending to it.
 */
@Composable
fun HomeScreen(vm: HomeViewModel, onNavigate: (Int) -> Unit) {
    LaunchedEffect(Unit) { vm.refresh() }

    val scheme = MaterialTheme.colorScheme
    // Ember palette. Warm and desaturated so the Sun reads as a light source
    // rather than a control — except under night vision, where the whole
    // scheme is red and the ember must simply sit dimmer than the interface.
    val nightVision = scheme.primary.red > 0.9f && scheme.primary.green < 0.3f
    val sunCore = if (nightVision) Color(0xFFB03A3A) else Color(0xFFC99A6B)
    val sunMid = if (nightVision) Color(0xFF7A2020) else Color(0xFF9E6F4A)
    val sunLimb = if (nightVision) Color(0xFF3A0E0E) else Color(0xFF5E4030)

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val k = minOf(maxWidth / DESIGN_W.dp, maxHeight / DESIGN_H.dp)
        val padX = (maxWidth - DESIGN_W.dp * k) / 2
        val padY = (maxHeight - DESIGN_H.dp * k) / 2

        Canvas(Modifier.fillMaxSize()) {
            val s = minOf(size.width / DESIGN_W, size.height / DESIGN_H)
            val ox = (size.width - DESIGN_W * s) / 2f
            val oy = (size.height - DESIGN_H * s) / 2f
            translate(ox, oy) {
                scale(s, s, pivot = Offset.Zero) {
                    drawSun(sunCore, sunMid, sunLimb)
                    drawEllipse(Offset(42f, 160f), 74f, 120f, scheme.outline, 0.8f)
                    drawEllipse(
                        Offset(42f, 160f), 100f, 84f,
                        scheme.primary.copy(alpha = 0.42f), 1f,
                    )
                }
            }
        }

        // Tonight's numbers, on the Sun's shadowed interior.
        Column(
            Modifier
                .offset(x = padX + 9.dp * k, y = padY + 118.dp * k)
                .semantics { contentDescription = "Tonight's observing conditions" },
        ) {
            Text(
                "TONIGHT",
                style = MaterialTheme.typography.labelSmall,
                color = sunCore,
                fontSize = (6.4f * k).designSp(),
                letterSpacing = (0.18f * 6.4f * k).designSp(),
            )
            val t = vm.tonight
            Text(
                t?.darkLabel ?: if (vm.error.isEmpty()) "…" else "—",
                style = MaterialTheme.typography.headlineSmall,
                color = scheme.onSurface,
                fontFamily = FontFamily.Monospace,
                fontSize = (16f * k).designSp(),
            )
            if (t != null) {
                Text(
                    "dark ${t.darkStart}–${t.darkEnd}",
                    color = scheme.onSurface.copy(alpha = 0.82f),
                    fontFamily = FontFamily.Monospace,
                    fontSize = (6.8f * k).designSp(),
                )
                Text(
                    "${t.moonLabel} · ${t.moonUp}",
                    color = scheme.onSurface.copy(alpha = 0.82f),
                    fontFamily = FontFamily.Monospace,
                    fontSize = (6.8f * k).designSp(),
                )
            }
            if (vm.siteLabel.isNotEmpty()) {
                Text(
                    vm.siteLabel,
                    color = scheme.primary,
                    fontSize = (6.8f * k).designSp(),
                )
            }
            if (vm.error.isNotEmpty()) {
                Text(
                    vm.error,
                    color = scheme.error,
                    fontSize = (6.2f * k).designSp(),
                )
            }
        }

        // Planets: real composables, so labels scale and tap targets are honest.
        PLANETS.forEach { p ->
            PlanetButton(
                planet = p,
                k = k,
                padX = padX,
                padY = padY,
                onClick = { onNavigate(p.tabIndex) },
            )
        }
    }
}

@Composable
private fun PlanetButton(
    planet: Planet,
    k: Float,
    padX: androidx.compose.ui.unit.Dp,
    padY: androidx.compose.ui.unit.Dp,
    onClick: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val tint = if (planet.subdued) scheme.onSurfaceVariant else scheme.primary
    // Touch target: at least 48dp regardless of how small the drawn disc is.
    val disc = (planet.r * 2f).dp * k
    val target = maxOf(disc, 48.dp)
    val half = target / 2

    Box(
        Modifier
            .offset(x = padX + planet.cx.dp * k - half, y = padY + planet.cy.dp * k - half)
            .size(target)
            .clip(CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Box(
                Modifier
                    .size(disc)
                    .clip(CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    planet.icon,
                    contentDescription = planet.label,
                    tint = tint,
                    modifier = Modifier.size(disc * 0.62f),
                )
            }
        }
    }
    if (!planet.subdued) {
        Text(
            planet.label,
            color = scheme.onSurface,
            textAlign = TextAlign.Center,
            fontSize = (8.4f * k).designSp(),
            modifier = Modifier
                .offset(
                    x = padX + planet.cx.dp * k - 30.dp,
                    y = padY + (planet.cy + planet.r).dp * k + 4.dp,
                )
                .size(width = 60.dp, height = 14.dp * maxOf(k, 1f)),
        )
    }
}

// ---- design-space geometry ------------------------------------------------

private const val DESIGN_W = 160f
private const val DESIGN_H = 320f

/**
 * A design-space type size, scaled by the same factor as the geometry.
 *
 * Expressed in sp so the viewer's font-size preference still applies: the
 * scale factor keeps the composition proportional, it does not opt out of
 * accessibility scaling.
 */
private fun Float.designSp(): TextUnit = TextUnit(this, TextUnitType.Sp)

private data class Planet(
    val label: String,
    val cx: Float,
    val cy: Float,
    val r: Float,
    val icon: ImageVector,
    val tabIndex: Int,
    val subdued: Boolean = false,
)

/**
 * Positions match the approved mockup. [tabIndex] is the index in
 * [MainActivity]'s tab list, where Home is 0 — so the planets start at 1.
 */
private val PLANETS: List<Planet>
    @Composable get() = listOf(
        Planet("Horizon", 100f, 60f, 15f, HorizonIcon, tabIndex = 1),
        Planet("Plan", 126f, 152f, 16f, Icons.AutoMirrored.Filled.List, tabIndex = 2),
        Planet("Align", 84f, 234f, 15f, CompassRoseIcon, tabIndex = 3),
        Planet("Settings", 132f, 286f, 12f, Icons.Filled.Settings, tabIndex = 4, subdued = true),
    )

private fun DrawScope.drawSun(core: Color, mid: Color, limb: Color) {
    // Cropped to the left 58 design-units: the Sun's centre is off-screen, so
    // only its right-hand crescent is ever visible.
    clipRect(right = 58f, clipOp = ClipOp.Intersect) {
        drawCircle(
            brush = Brush.horizontalGradient(
                0.00f to limb.copy(alpha = 0.10f),
                0.62f to limb.copy(alpha = 0.30f),
                0.88f to mid.copy(alpha = 0.62f),
                1.00f to core.copy(alpha = 0.92f),
                startX = -172f,
                endX = 56f,
            ),
            radius = 114f,
            center = Offset(-58f, 160f),
        )
        // the lit limb itself — thin, and the brightest thing in the arc
        drawCircle(
            color = core.copy(alpha = 0.85f),
            radius = 114f,
            center = Offset(-58f, 160f),
            style = Stroke(width = 1.8f),
        )
    }
}

private fun DrawScope.drawEllipse(
    center: Offset,
    rx: Float,
    ry: Float,
    color: Color,
    width: Float,
) {
    drawOval(
        color = color,
        topLeft = Offset(center.x - rx, center.y - ry),
        size = Size(rx * 2, ry * 2),
        style = Stroke(width = width),
    )
}
