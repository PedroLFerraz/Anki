package com.pedrolopes.ankigen.ui.cards

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pedrolopes.ankigen.data.anki.AnkiDroidExporter
import com.pedrolopes.ankigen.data.model.CardStatus
import com.pedrolopes.ankigen.data.model.CardType
import com.pedrolopes.ankigen.ui.components.CardItem

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
            title = { Text("AnkiDroid not found") },
            text = { Text("Install AnkiDroid to send cards straight into your collection.") },
            confirmButton = {
                TextButton(onClick = vm::dismissAnkiDroidMissing) { Text("OK") }
            },
        )
    }

    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
    ) {

        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FilterDropdown(
                label = state.statusFilter ?: "All statuses",
                options = CardStatus.selectable,
                onSelect = vm::setStatusFilter,
            )
            FilterDropdown(
                label = state.typeFilter?.let(CardType::label) ?: "All types",
                options = CardType.all,
                optionLabel = CardType::label,
                onSelect = vm::setTypeFilter,
            )
            FilterDropdown(
                label = state.topicFilter ?: "All topics",
                options = state.topics,
                onSelect = vm::setTopicFilter,
            )
        }

        Spacer(Modifier.height(8.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${state.cards.size} cards" +
                    if (state.selected.isNotEmpty()) " · ${state.selected.size} selected" else "",
                style = MaterialTheme.typography.titleMedium,
            )
            Spacer(Modifier.weight(1f))
            if (state.selected.isEmpty()) {
                TextButton(onClick = vm::selectAllVisible) { Text("Select all") }
            } else {
                TextButton(onClick = vm::clearSelection) { Text("Clear") }
            }
        }

        if (state.selected.isNotEmpty()) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { vm.bulkStatus(CardStatus.ACCEPTED) },
                    modifier = Modifier.weight(1f),
                ) { Text("Accept") }
                OutlinedButton(
                    onClick = { vm.bulkStatus(CardStatus.REJECTED) },
                    modifier = Modifier.weight(1f),
                ) { Text("Reject") }
            }
        }

        OutlinedButton(
            onClick = vm::sendToAnkiDroid,
            enabled = !state.isSending,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (state.isSending) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                Spacer(Modifier.size(8.dp))
                Text("Sending...")
            } else {
                val n = state.selected.size.takeIf { it > 0 }
                Text(if (n != null) "Send $n to AnkiDroid" else "Send accepted to AnkiDroid")
            }
        }

        Spacer(Modifier.height(10.dp))

        if (state.isLoading && state.cards.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else if (state.cards.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    "No cards match these filters.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(state.cards, key = { it.id }) { card ->
                    CardItem(
                        card = card,
                        imageUrl = vm.imageUrl(card),
                        selected = card.id in state.selected,
                        onSelectedChange = { vm.toggleSelection(card.id) },
                        onAccept = if (card.status != CardStatus.ACCEPTED) {
                            { vm.setStatus(card, CardStatus.ACCEPTED) }
                        } else null,
                        onReject = if (card.status != CardStatus.REJECTED) {
                            { vm.setStatus(card, CardStatus.REJECTED) }
                        } else null,
                        onDelete = { vm.delete(card) },
                    )
                }
                item { Spacer(Modifier.height(24.dp)) }
            }
        }
    }
}

@Composable
private fun FilterDropdown(
    label: String,
    options: List<String>,
    onSelect: (String?) -> Unit,
    optionLabel: (String) -> String = { it },
) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        AssistChip(
            onClick = { expanded = true },
            label = { Text(label) },
            trailingIcon = { Icon(Icons.Default.ArrowDropDown, contentDescription = null) },
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(
                text = { Text("All") },
                onClick = {
                    onSelect(null)
                    expanded = false
                },
            )
            options.forEach { option ->
                DropdownMenuItem(
                    text = { Text(optionLabel(option)) },
                    onClick = {
                        onSelect(option)
                        expanded = false
                    },
                )
            }
        }
    }
}
