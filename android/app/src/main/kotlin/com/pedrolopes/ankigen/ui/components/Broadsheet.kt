package com.pedrolopes.ankigen.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pedrolopes.ankigen.ui.theme.AnswerStyle
import com.pedrolopes.ankigen.ui.theme.CardKickerStyle
import com.pedrolopes.ankigen.ui.theme.Cyan
import com.pedrolopes.ankigen.ui.theme.Divider
import com.pedrolopes.ankigen.ui.theme.Ink
import com.pedrolopes.ankigen.ui.theme.KickerStyle
import com.pedrolopes.ankigen.ui.theme.Magenta
import com.pedrolopes.ankigen.ui.theme.Magenta700
import com.pedrolopes.ankigen.ui.theme.Paper
import com.pedrolopes.ankigen.ui.theme.PaperSurface
import com.pedrolopes.ankigen.ui.theme.SourceSerif4
import com.pedrolopes.ankigen.ui.theme.ink

private val RadiusMd = RoundedCornerShape(2.dp)

/** `.kick` — the system's small-caps label. Always uppercased. */
@Composable
fun Kicker(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = ink(0.5f),
) {
    Text(
        text.uppercase(),
        modifier = modifier,
        style = KickerStyle,
        color = color,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

/** `.btn.btn-primary` — solid cyan, paper text. */
@Composable
fun PrimaryButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    height: Int = 46,
    fontSize: Int = 15,
    loading: Boolean = false,
) {
    Box(
        modifier
            .height(height.dp)
            .background(if (enabled) Cyan else Cyan.copy(alpha = 0.35f), RadiusMd)
            .clickable(enabled = enabled && !loading, onClick = onClick)
            .padding(horizontal = 18.dp),
        contentAlignment = Alignment.Center,
    ) {
        if (loading) {
            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = Paper)
        } else {
            Text(
                label,
                style = TextStyle(
                    fontFamily = SourceSerif4,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = fontSize.sp,
                ),
                color = Paper,
            )
        }
    }
}

/** `.btn.btn-secondary` — hairline rule, ink text. */
@Composable
fun SecondaryButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    height: Int = 46,
    fontSize: Int = 15,
    color: Color = Ink,
) {
    Box(
        modifier
            .height(height.dp)
            .border(1.dp, Divider, RadiusMd)
            .clickable(onClick = onClick)
            .padding(horizontal = 18.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            style = TextStyle(
                fontFamily = SourceSerif4,
                fontWeight = FontWeight.SemiBold,
                fontSize = fontSize.sp,
            ),
            color = color,
        )
    }
}

/**
 * The card-type row: inline serif words, the active one cyan and ruled.
 * Broadsheet has no pill chips — selection is an underline.
 */
@Composable
fun TypeRow(
    types: List<String>,
    labels: (String) -> String,
    selected: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    trailing: @Composable (() -> Unit)? = null,
) {
    Row(
        modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        types.forEach { type ->
            val on = type == selected
            Column(
                Modifier
                    .width(IntrinsicSize.Min)
                    .clickable { onSelect(type) },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    labels(type),
                    style = TextStyle(
                        fontFamily = SourceSerif4,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 13.sp,
                    ),
                    color = if (on) Cyan else ink(0.45f),
                )
                if (on) {
                    Spacer(Modifier.height(2.dp))
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .height(1.5.dp)
                            .background(Cyan),
                    )
                }
            }
        }
        if (trailing != null) {
            Spacer(Modifier.weight(1f))
            trailing()
        }
    }
}

/**
 * `.input` paired with an icon button — the compose bar that sits at the
 * thumb in the Press desk layout.
 */
@Composable
fun ComposeBar(
    value: String,
    onValueChange: (String) -> Unit,
    onSubmit: () -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "Topic to generate from",
    height: Int = 46,
    fontSize: Int = 15,
    enabled: Boolean = true,
    loading: Boolean = false,
    accent: Boolean = true,
) {
    Row(
        modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(
            Modifier
                .weight(1f)
                .height(height.dp)
                .border(1.dp, ink(0.25f), RadiusMd)
                .padding(horizontal = 10.dp),
            contentAlignment = Alignment.CenterStart,
        ) {
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = true,
                textStyle = LocalTextStyle.current.copy(
                    fontFamily = SourceSerif4,
                    fontSize = fontSize.sp,
                    color = Ink,
                ),
                cursorBrush = SolidColor(Cyan),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
                keyboardActions = KeyboardActions(onGo = { onSubmit() }),
                modifier = Modifier.fillMaxWidth(),
                decorationBox = { inner ->
                    if (value.isEmpty()) {
                        Text(
                            placeholder,
                            style = TextStyle(
                                fontFamily = SourceSerif4,
                                fontSize = fontSize.sp,
                            ),
                            color = ink(0.65f),
                        )
                    }
                    inner()
                },
            )
        }

        Box(
            Modifier
                .size(height.dp)
                .then(
                    if (accent) Modifier.background(if (enabled) Cyan else Cyan.copy(alpha = 0.35f), RadiusMd)
                    else Modifier.border(1.dp, Divider, RadiusMd)
                )
                .clickable(enabled = enabled && !loading, onClick = onSubmit),
            contentAlignment = Alignment.Center,
        ) {
            if (loading) {
                CircularProgressIndicator(
                    Modifier.size(18.dp),
                    strokeWidth = 2.dp,
                    color = if (accent) Paper else Cyan,
                )
            } else {
                Icon(
                    Icons.Default.AutoAwesome,
                    contentDescription = "Generate",
                    tint = if (accent) Paper else Cyan,
                    modifier = Modifier.size(if (height >= 46) 22.dp else 20.dp),
                )
            }
        }
    }
}

/** How a slip has been triaged, which drives its rule colour and marker. */
enum class SlipState { Kept, Dropped, Waiting }

/**
 * A proof slip — the unit of the Press desk review grid. A ruled top edge
 * carries the verdict: cyan kept, magenta dropped, nothing while waiting.
 */
@Composable
fun Slip(
    kicker: String,
    question: String,
    answer: String,
    state: SlipState,
    modifier: Modifier = Modifier,
    isDuplicate: Boolean = false,
    onKeep: (() -> Unit)? = null,
    onDrop: (() -> Unit)? = null,
) {
    val rule = when {
        isDuplicate -> Magenta
        state == SlipState.Kept -> Cyan
        state == SlipState.Dropped -> Magenta
        else -> Color.Transparent
    }

    Column(
        modifier
            .then(if (state == SlipState.Dropped || isDuplicate) Modifier.alpha(0.5f) else Modifier)
            .background(PaperSurface, RadiusMd),
    ) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(2.dp)
                .background(rule),
        )
        Column(
            Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    (if (isDuplicate) "Duplicate" else kicker).uppercase(),
                    style = CardKickerStyle,
                    color = if (isDuplicate) Magenta700 else Cyan,
                )
                when {
                    isDuplicate || state == SlipState.Dropped ->
                        Icon(Icons.Default.Close, "Dropped", tint = Magenta, modifier = Modifier.size(16.dp))
                    state == SlipState.Kept ->
                        Icon(Icons.Default.Check, "Kept", tint = Cyan, modifier = Modifier.size(16.dp))
                    else -> Kicker("waiting")
                }
            }

            Text(
                question,
                style = TextStyle(
                    fontFamily = SourceSerif4,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 14.sp,
                    lineHeight = 17.5.sp,
                    textDecoration = if (isDuplicate) TextDecoration.LineThrough else null,
                ),
                color = Ink,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )

            if (answer.isNotBlank()) {
                Text(
                    answer,
                    style = AnswerStyle.copy(fontSize = 12.sp, lineHeight = 18.sp),
                    color = ink(0.62f),
                    maxLines = 4,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            if (state == SlipState.Waiting && !isDuplicate && onKeep != null && onDrop != null) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(top = 2.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    SecondaryButton(
                        "Drop", onDrop,
                        modifier = Modifier.weight(1f),
                        height = 30, fontSize = 12, color = Magenta700,
                    )
                    PrimaryButton(
                        "Keep", onKeep,
                        modifier = Modifier.weight(1f),
                        height = 30, fontSize = 12,
                    )
                }
            }
        }
    }
}

/** A run on the desk's "Recent runs" list. */
@Composable
fun RunRow(topic: String, detail: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            topic,
            style = TextStyle(
                fontFamily = SourceSerif4,
                fontWeight = FontWeight.SemiBold,
                fontSize = 15.sp,
            ),
            color = Ink,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false),
        )
        Spacer(Modifier.width(10.dp))
        Kicker(detail)
    }
}

/** Body copy in the system's italic voice, used for the back of a card. */
@Composable
fun AnswerText(text: String, modifier: Modifier = Modifier, italic: Boolean = false) {
    Text(
        text,
        modifier = modifier,
        style = AnswerStyle.copy(fontStyle = if (italic) FontStyle.Italic else FontStyle.Normal),
        color = ink(0.62f),
    )
}
