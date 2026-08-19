package com.pedrolopes.ankigen.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Carried over from the web frontend so both surfaces read as one product.
val Accent = Color(0xFF4FC3F7)
val AccentDim = Color(0xFF2E7A9E)
val Surface1 = Color(0xFF1A1A2E)
val Surface2 = Color(0xFF222240)
val BackgroundDark = Color(0xFF0F0F1A)
val BorderDark = Color(0xFF2D2D50)
val TextDim = Color(0xFF8888AA)

val StatusGreen = Color(0xFF66BB6A)
val StatusRed = Color(0xFFEF5350)
val StatusOrange = Color(0xFFFFA726)
val StatusPurple = Color(0xFFAB47BC)

private val DarkColors = darkColorScheme(
    primary = Accent,
    onPrimary = Color.Black,
    primaryContainer = AccentDim,
    onPrimaryContainer = Color.White,
    secondary = StatusPurple,
    background = BackgroundDark,
    onBackground = Color(0xFFE0E0E0),
    surface = Surface1,
    onSurface = Color(0xFFE0E0E0),
    surfaceVariant = Surface2,
    onSurfaceVariant = TextDim,
    outline = BorderDark,
    error = StatusRed,
)

private val LightColors = lightColorScheme(
    primary = AccentDim,
    onPrimary = Color.White,
    secondary = StatusPurple,
    error = StatusRed,
)

private val AppTypography = Typography(
    titleLarge = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.Medium),
    bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelSmall = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Bold),
)

@Composable
fun AnkiGenTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = AppTypography,
        content = content,
    )
}

/** Accent colour for a card status chip. */
fun statusColor(status: String): Color = when (status) {
    "ACCEPTED" -> StatusGreen
    "REJECTED" -> StatusRed
    "DUPLICATE" -> StatusOrange
    "EXPORTED" -> StatusPurple
    else -> TextDim
}

/** Accent colour for a card-type badge. */
fun cardTypeColor(cardType: String): Color = when (cardType) {
    "detailed" -> StatusPurple
    "visual" -> StatusOrange
    "cloze" -> StatusGreen
    else -> Accent
}
