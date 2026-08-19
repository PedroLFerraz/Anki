package com.pedrolopes.ankigen.ui.cards

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pedrolopes.ankigen.data.anki.AnkiDroidExporter
import com.pedrolopes.ankigen.data.model.CardStatus
import com.pedrolopes.ankigen.data.model.CardType
import com.pedrolopes.ankigen.ui.components.CardItem
import com.pedrolopes.ankigen.ui.components.Kicker
import com.pedrolopes.ankigen.ui.components.PrimaryButton
import com.pedrolopes.ankigen.ui.components.SecondaryButton
import com.pedrolopes.ankigen.ui.theme.Cyan
import com.pedrolopes.ankigen.ui.theme.Cyan700
import com.pedrolopes.ankigen.ui.theme.Ink
import com.pedrolopes.ankigen.ui.theme.Magenta700
import com.pedrolopes.ankigen.ui.theme.ink

/**
 * The collection, set as running text. Filters read as a sentence rather than
 * a row of chips — each underlined term opens its own menu.
 */
@Composable
fun CardsScreen(
    onMessage: (String) -> Unit,
    vm: CardsViewModel = viewModel(),
) {
    val state by vm.state.collectAsStateWithLifecycle()

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> vm.onPermissionResult(granted) }

    LaunchedEffect(state.needsPermission) {
        if (state.needsPermission) {
            permissionLauncher.launch(AnkiDroidExporter.READ_WRITE_PERMISSION)
        }
    }

    LaunchedEffect(state.message, state.error) {
        (state.error ?: state.message)?.let {
            onMessage(it)
            vm.dismissMessage()
        }
    }

    if (state.ankiDroidMissing) {
        AlertDialog(
            onDismissRequest = vm::dismissAnkiDroidMissing,
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
            title = { Text("AnkiDroid not found", style = MaterialTheme.typography.titleMedium) },
            text = {
                Text(
                    "Install AnkiDroid to send cards straight into your collection.",
                    style = MaterialTheme.typography.bodyMedium,
                )
            },
            confirmButton = {
                TextButton(onClick = vm::dismissAnkiDroidMissing) { Text("OK") }
            },
        )
    }

    Column(Modifier.fillMaxSize()) {

        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(top = 14.dp),
        ) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Bottom,
            ) {
                Kicker("AnkiGen · Cards")
                Kicker(
                    if (state.selected.isEmpty()) "Select all" else "Clear",
                    color = Cyan700,
                    modifier = Modifier.clickable {
                        if (state.selected.isEmpty()) vm.selectAllVisible() else vm.clearSelection()
                    },
                )
            }

            Spacer(Modifier.height(12.dp))
            Text(
                headline(state),
                style = MaterialTheme.typography.titleLarge.copy(fontSize = 24.sp),
                color = Ink,
            )

            Spacer(Modifier.height(6.dp))
            FilterSentence(state, vm)
        }

        Spacer(Modifier.height(20.dp))

        when {
            state.isLoading && state.cards.isEmpty() ->
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = Cyan)
                }

            state.cards.isEmpty() ->
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Text(
                        "Nothing matches those filters.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = ink(0.55f),
                    )
                }

            else -> LazyColumn(
                Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                items(state.cards, key = { it.id }) { card ->
                    CardItem(
                        card = card,
                        imageUrl = vm.imageUrl(card),
                        selected = card.id in state.selected,
                        onClick = { vm.toggleSelection(card.id) },
                        showStatus = state.statusFilter == null,
                    )
                }
                item { Spacer(Modifier.height(4.dp)) }
            }
        }

        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 12.dp),
        ) {
            if (state.selected.isNotEmpty()) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    SecondaryButton(
                        "Drop", { vm.bulkStatus(CardStatus.REJECTED) },
                        modifier = Modifier.weight(1f), height = 42, fontSize = 14,
                        color = Magenta700,
                    )
                    SecondaryButton(
                        "Keep", { vm.bulkStatus(CardStatus.ACCEPTED) },
                        modifier = Modifier.weight(1f), height = 42, fontSize = 14,
                        color = Cyan700,
                    )
                }
                Spacer(Modifier.height(8.dp))
            }
            PrimaryButton(
                label = if (state.selected.isNotEmpty()) "Send ${state.selected.size} to AnkiDroid"
                else "Send accepted to AnkiDroid",
                onClick = vm::sendToAnkiDroid,
                modifier = Modifier.fillMaxWidth(),
                height = 42,
                fontSize = 14,
                loading = state.isSending,
            )
        }
    }
}

private fun headline(state: CardsUiState): String {
    val n = state.cards.size
    val status = state.statusFilter?.lowercase()
    return when {
        state.selected.isNotEmpty() -> "${state.selected.size} selected"
        status != null -> "$n $status"
        else -> "$n card${if (n == 1) "" else "s"}"
    }
}

/**
 * "Filtered to accepted, all types, Roman Republic." Each underlined term is
 * its own menu — the filters read rather than stack up as controls.
 */
@Composable
private fun FilterSentence(state: CardsUiState, vm: CardsViewModel) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            "Filtered to ",
            style = MaterialTheme.typography.bodyMedium,
            color = ink(0.62f),
        )
        FilterTerm(
            label = state.statusFilter?.lowercase() ?: "any status",
            options = CardStatus.selectable,
            optionLabel = { it.lowercase() },
            onSelect = vm::setStatusFilter,
        )
        Text(", ", style = MaterialTheme.typography.bodyMedium, color = ink(0.62f))
        FilterTerm(
            label = state.typeFilter?.let(CardType::label)?.lowercase() ?: "all types",
            options = CardType.all,
            optionLabel = { CardType.label(it).lowercase() },
            onSelect = vm::setTypeFilter,
        )
        if (state.topics.isNotEmpty()) {
            Text(", ", style = MaterialTheme.typography.bodyMedium, color = ink(0.62f))
            FilterTerm(
                label = state.topicFilter ?: "all topics",
                options = state.topics,
                optionLabel = { it },
                onSelect = vm::setTopicFilter,
            )
        }
    }
}

@Composable
private fun FilterTerm(
    label: String,
    options: List<String>,
    optionLabel: (String) -> String,
    onSelect: (String?) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        Text(
            underlined(label),
            style = MaterialTheme.typography.bodyMedium,
            color = Cyan700,
            modifier = Modifier.clickable { expanded = true },
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(
                text = { Text("Any", style = MaterialTheme.typography.bodyMedium) },
                onClick = {
                    onSelect(null)
                    expanded = false
                },
            )
            options.forEach { option ->
                DropdownMenuItem(
                    text = {
                        Text(optionLabel(option), style = MaterialTheme.typography.bodyMedium)
                    },
                    onClick = {
                        onSelect(option)
                        expanded = false
                    },
                )
            }
        }
    }
}

private fun underlined(text: String): AnnotatedString = buildAnnotatedString {
    withStyle(SpanStyle(textDecoration = TextDecoration.Underline)) { append(text) }
}
