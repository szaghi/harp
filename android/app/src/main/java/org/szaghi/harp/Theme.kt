package org.szaghi.harp

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * App theming: one red night-vision scheme for use at the telescope, plus a
 * set of user-selectable indoor dark themes ported from the popular web
 * palettes (Tokyo Night, Catppuccin, Nord, ...).
 *
 * HARP is used in the dark. The light Material default destroys dark
 * adaptation, so there is no light theme: the choice is only *which* dark
 * one. [nightVision] takes precedence over the indoor selection — the field
 * mode is a hard toggle, not a palette option — because red-on-black above
 * ~620 nm is the only scheme that preserves scotopic vision at the eyepiece.
 *
 * Every palette is expressed as a Material3 [darkColorScheme] so all existing
 * screens re-theme for free through `MaterialTheme.colorScheme.*`.
 */

/** A selectable indoor theme: stable [id] persisted in settings, [label] shown in the picker. */
data class HarpTheme(
    val id: String,
    val label: String,
    val scheme: ColorScheme,
)

private fun scheme(
    bg: Long,
    surface: Long,
    line: Long,
    ink: Long,
    muted: Long,
    accent: Long,
    onAccent: Long,
    error: Long,
): ColorScheme = darkColorScheme(
    primary = Color(accent),
    onPrimary = Color(onAccent),
    secondary = Color(accent),
    onSecondary = Color(onAccent),
    background = Color(bg),
    onBackground = Color(ink),
    surface = Color(surface),
    onSurface = Color(ink),
    surfaceVariant = Color(line),
    onSurfaceVariant = Color(muted),
    outline = Color(line),
    outlineVariant = Color(line),
    error = Color(error),
    onError = Color(bg),
)

/** Red night-vision: pure red-on-black, the in-situ mode near the telescope. */
val NIGHT_VISION: ColorScheme = scheme(
    bg = 0xFF000000,
    surface = 0xFF0A0000,
    line = 0xFF3A0000,
    ink = 0xFFFF3B3B,
    muted = 0xFFA11414,
    accent = 0xFFFF2222,
    onAccent = 0xFF000000,
    error = 0xFFFF7A4D,
)

/**
 * The user-selectable indoor themes, ported from the approved mockups.
 * Order here is the picker order; the first entry is the default.
 */
val INDOOR_THEMES: List<HarpTheme> = listOf(
    HarpTheme(
        "tokyo_night", "Tokyo Night",
        scheme(
            bg = 0xFF1A1B26, surface = 0xFF1F2130, line = 0xFF2B2E44,
            ink = 0xFFC0CAF5, muted = 0xFF565F89, accent = 0xFF7AA2FF,
            onAccent = 0xFF0D0F1A, error = 0xFFF7768E,
        ),
    ),
    HarpTheme(
        "catppuccin_mocha", "Catppuccin Mocha",
        scheme(
            bg = 0xFF1E1E2E, surface = 0xFF242438, line = 0xFF313244,
            ink = 0xFFCDD6F4, muted = 0xFF7F849C, accent = 0xFF89B4FA,
            onAccent = 0xFF11111B, error = 0xFFF38BA8,
        ),
    ),
    HarpTheme(
        "nord", "Nord",
        scheme(
            bg = 0xFF2E3440, surface = 0xFF343B4A, line = 0xFF3B4252,
            ink = 0xFFECEFF4, muted = 0xFF7B8494, accent = 0xFF88C0D0,
            onAccent = 0xFF20242D, error = 0xFFBF616A,
        ),
    ),
    HarpTheme(
        "one_dark", "One Dark",
        scheme(
            bg = 0xFF282C34, surface = 0xFF2D323C, line = 0xFF3A3F4B,
            ink = 0xFFABB2BF, muted = 0xFF7D838F, accent = 0xFF61AFEF,
            onAccent = 0xFF1B1E24, error = 0xFFE06C75,
        ),
    ),
    HarpTheme(
        "dracula", "Dracula",
        scheme(
            bg = 0xFF282A36, surface = 0xFF2D2F3D, line = 0xFF3C3F52,
            ink = 0xFFF8F8F2, muted = 0xFF7B7F97, accent = 0xFFBD93F9,
            onAccent = 0xFF1A1B23, error = 0xFFFF5555,
        ),
    ),
    HarpTheme(
        "gruvbox_dark", "Gruvbox Dark",
        scheme(
            bg = 0xFF282828, surface = 0xFF32302F, line = 0xFF3C3836,
            ink = 0xFFEBDBB2, muted = 0xFF928374, accent = 0xFFFABD2F,
            onAccent = 0xFF1D2021, error = 0xFFFB4934,
        ),
    ),
    HarpTheme(
        "solarized_dark", "Solarized Dark",
        scheme(
            bg = 0xFF002B36, surface = 0xFF073642, line = 0xFF0E4B59,
            ink = 0xFF93A1A1, muted = 0xFF586E75, accent = 0xFF2AA198,
            onAccent = 0xFF00232C, error = 0xFFDC322F,
        ),
    ),
)

/** Default indoor theme id, used when settings carry no (or an unknown) selection. */
const val DEFAULT_INDOOR_THEME: String = "tokyo_night"

/** Resolve an indoor-theme id to its scheme, falling back to the default. */
fun indoorSchemeFor(id: String): ColorScheme =
    (INDOOR_THEMES.firstOrNull { it.id == id } ?: INDOOR_THEMES.first()).scheme

/**
 * Apply the active HARP theme. When [nightVision] is on, the red field scheme
 * wins regardless of the indoor selection; otherwise the user's chosen indoor
 * theme ([indoorThemeId]) is used.
 */
@Composable
fun HarpAppTheme(
    nightVision: Boolean,
    indoorThemeId: String,
    content: @Composable () -> Unit,
) {
    val scheme = if (nightVision) NIGHT_VISION else indoorSchemeFor(indoorThemeId)
    MaterialTheme(colorScheme = scheme, content = content)
}
