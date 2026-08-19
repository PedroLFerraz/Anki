package com.pedrolopes.ankigen.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * Broadsheet sets everything — headings and body — in Source Serif 4.
 *
 * This resolves to the platform serif rather than the real face. Google's
 * downloadable-font provider needs a certificate array that the
 * ui-text-google-fonts artifact does not ship, and bundling the TTF means
 * adding a binary to the repo. The platform serif (Noto Serif on most
 * devices) is the same transitional genre, so the type reads as intended.
 *
 * To use the real face: drop SourceSerif4[opsz,wght].ttf into res/font/ and
 * change this one declaration to FontFamily(Font(R.font.source_serif_4)).
 * Nothing else in the app refers to the family directly.
 */
val SourceSerif4: FontFamily = FontFamily.Serif

/** Display/heading face: 600 weight, tight leading, slight negative tracking. */
fun heading(size: Int, lineHeight: Float = 1.15f, tracking: Float = -0.015f) = TextStyle(
    fontFamily = SourceSerif4,
    fontWeight = FontWeight.SemiBold,
    fontSize = size.sp,
    lineHeight = (size * lineHeight).sp,
    letterSpacing = (size * tracking).sp,
)

/** Running text: 400 weight, 1.5-1.55 leading. */
fun body(size: Int, lineHeight: Float = 1.5f) = TextStyle(
    fontFamily = SourceSerif4,
    fontWeight = FontWeight.Normal,
    fontSize = size.sp,
    lineHeight = (size * lineHeight).sp,
)

/**
 * The `.kick` class — the system's small caps label. 10px, wide tracking,
 * uppercased at the call site.
 */
val KickerStyle = TextStyle(
    fontFamily = SourceSerif4,
    fontWeight = FontWeight.Normal,
    fontSize = 10.sp,
    lineHeight = 13.sp,
    letterSpacing = 1.1.sp,
)

/** The `.card-kicker` class — as above but tighter and set in cyan. */
val CardKickerStyle = KickerStyle.copy(letterSpacing = 1.0.sp)

/** `.q` — the question line on a slip. */
val QuestionStyle = TextStyle(
    fontFamily = SourceSerif4,
    fontWeight = FontWeight.SemiBold,
    fontSize = 16.5.sp,
    lineHeight = 20.5.sp,
    letterSpacing = (-0.165).sp,
)

/** `.a` — the answer line, quieter than the question. */
val AnswerStyle = body(13)

val BroadsheetTypography = Typography(
    displayLarge = heading(42),
    displayMedium = heading(34, lineHeight = 1.08f, tracking = -0.02f),
    headlineLarge = heading(32, tracking = -0.02f),
    headlineMedium = heading(28, lineHeight = 1.16f),
    headlineSmall = heading(25),
    titleLarge = heading(23, tracking = -0.02f),
    titleMedium = heading(20),
    titleSmall = heading(16),
    bodyLarge = body(15, lineHeight = 1.55f),
    bodyMedium = body(13),
    bodySmall = body(12),
    labelLarge = TextStyle(
        fontFamily = SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 17.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = SourceSerif4,
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        lineHeight = 16.sp,
    ),
    labelSmall = KickerStyle,
)
