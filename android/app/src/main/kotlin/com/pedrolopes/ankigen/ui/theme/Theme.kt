package com.pedrolopes.ankigen.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Broadsheet — the design system from the AnkiGen Redesign canvas.
 *
 * Paper ground, one ink, cyan as the only interactive colour and magenta
 * reserved for rejects. Values are lifted verbatim from the system's
 * styles.css so the app and the canvas stay in register.
 */

// --- ground and ink ---
val Paper = Color(0xFFF3F2F2)          // --color-bg
val PaperSurface = Color(0xFFEAE9E9)   // --color-surface
val Ink = Color(0xFF201E1D)            // --color-text

// --- cyan: the only interactive ink ---
val Cyan = Color(0xFF0088B0)           // --color-accent
val Cyan600 = Color(0xFF1186AC)
val Cyan700 = Color(0xFF006786)        // --color-accent-700
val Cyan100 = Color(0xFFE9F8FF)

// --- magenta: rejects and duplicates only, never chrome ---
val Magenta = Color(0xFFD6006C)        // --color-accent-2
val Magenta700 = Color(0xFFAA0B56)     // --color-accent-2-700
val Magenta100 = Color(0xFFFFF1F4)

/** `color-mix(in srgb, var(--color-text) N%, transparent)` from the stylesheet. */
fun ink(fraction: Float): Color = Ink.copy(alpha = fraction)

val Divider = ink(0.16f)               // --color-divider

// The stylesheet's spacing scale, in dp.
object Space {
    const val S1 = 5
    const val S2 = 10
    const val S3 = 15
    const val S4 = 20
    const val S6 = 30
    const val S8 = 40
}

private val BroadsheetColors = lightColorScheme(
    primary = Cyan,
    onPrimary = Paper,
    primaryContainer = Cyan100,
    onPrimaryContainer = Cyan700,
    secondary = Magenta,
    onSecondary = Paper,
    secondaryContainer = Magenta100,
    onSecondaryContainer = Magenta700,
    background = Paper,
    onBackground = Ink,
    surface = Paper,
    onSurface = Ink,
    surfaceVariant = PaperSurface,
    onSurfaceVariant = ink(0.62f),
    outline = Divider,
    outlineVariant = Divider,
    error = Magenta,
    onError = Paper,
)

@Composable
fun AnkiGenTheme(content: @Composable () -> Unit) {
    // Broadsheet is a paper system; it does not have a dark counterpart, so
    // the scheme is committed rather than following the system setting.
    MaterialTheme(
        colorScheme = BroadsheetColors,
        typography = BroadsheetTypography,
        content = content,
    )
}

/** Rule colour for a card status: cyan keeps, magenta drops, ink for the rest. */
fun statusColor(status: String): Color = when (status) {
    "ACCEPTED" -> Cyan
    "REJECTED", "DUPLICATE" -> Magenta
    "EXPORTED" -> Cyan700
    else -> ink(0.45f)
}

/** Three-letter setting used in the canvas's card lists ("Bas", "Det", "Clz"). */
fun cardTypeAbbrev(cardType: String): String = when (cardType) {
    "detailed" -> "Det"
    "visual" -> "Vis"
    "cloze" -> "Clz"
    else -> "Bas"
}
