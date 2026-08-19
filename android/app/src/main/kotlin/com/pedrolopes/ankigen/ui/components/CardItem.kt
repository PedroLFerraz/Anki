package com.pedrolopes.ankigen.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.pedrolopes.ankigen.data.model.backText
import com.pedrolopes.ankigen.data.model.frontText
import com.pedrolopes.ankigen.ui.theme.AnswerStyle
import com.pedrolopes.ankigen.ui.theme.Cyan
import com.pedrolopes.ankigen.ui.theme.Ink
import com.pedrolopes.ankigen.ui.theme.QuestionStyle
import com.pedrolopes.ankigen.ui.theme.SourceSerif4
import com.pedrolopes.ankigen.ui.theme.cardTypeAbbrev
import com.pedrolopes.ankigen.ui.theme.ink
import com.pedrolopes.ankigen.ui.theme.statusColor
import com.pedrolopes.ankigen.data.model.Card as CardModel

/**
 * One row in the Cards list.
 *
 * Broadsheet sets these as running text rather than boxes: question, answer,
 * and a three-letter type setting in the right margin. Selection is a cyan
 * rule in the left gutter, not a checkbox.
 */
@Composable
fun CardItem(
    card: CardModel,
    imageUrl: String?,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
    showStatus: Boolean = false,
) {
    Row(
        modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        // Left gutter: carries the selection rule, and keeps text aligned
        // whether or not anything is selected.
        Box(
            Modifier
                .width(2.dp)
                .height(if (selected) 44.dp else 0.dp)
                .background(if (selected) Cyan else Color.Transparent),
        )

        Column(Modifier.weight(1f)) {
            if (imageUrl != null) {
                AsyncImage(
                    model = imageUrl,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(120.dp)
                        .clip(RoundedCornerShape(2.dp)),
                )
                Spacer(Modifier.height(6.dp))
            }

            Text(
                card.frontText,
                style = QuestionStyle,
                color = Ink,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            if (card.backText.isNotBlank()) {
                Spacer(Modifier.height(3.dp))
                Text(
                    card.backText,
                    style = AnswerStyle,
                    color = ink(0.62f),
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (showStatus) {
                Spacer(Modifier.height(3.dp))
                Kicker(card.status, color = statusColor(card.status))
            }
        }

        Row(
            Modifier.padding(top = 3.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (selected) {
                Icon(Icons.Default.Check, "Selected", tint = Cyan, modifier = Modifier.size(14.dp))
            }
            Text(
                cardTypeAbbrev(card.cardType),
                style = TextStyle(
                    fontFamily = SourceSerif4,
                    fontWeight = FontWeight.Normal,
                    fontSize = 10.sp,
                    letterSpacing = 1.1.sp,
                ),
                color = ink(0.5f),
            )
        }
    }
}
