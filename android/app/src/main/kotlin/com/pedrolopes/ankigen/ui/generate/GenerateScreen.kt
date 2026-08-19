package com.pedrolopes.ankigen.ui.generate

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pedrolopes.ankigen.data.anki.AnkiDroidExporter
import com.pedrolopes.ankigen.data.model.Card
import com.pedrolopes.ankigen.data.model.CardStatus
import com.pedrolopes.ankigen.data.model.CardType
import com.pedrolopes.ankigen.data.model.backText
import com.pedrolopes.ankigen.data.model.frontText
import com.pedrolopes.ankigen.ui.components.ComposeBar
import com.pedrolopes.ankigen.ui.components.Kicker
import com.pedrolopes.ankigen.ui.components.PrimaryButton
import com.pedrolopes.ankigen.ui.components.RunRow
import com.pedrolopes.ankigen.ui.components.Slip
import com.pedrolopes.ankigen.ui.components.SlipState
import com.pedrolopes.ankigen.ui.components.TypeRow
import com.pedrolopes.ankigen.ui.theme.Cyan
import com.pedrolopes.ankigen.ui.theme.Ink
import com.pedrolopes.ankigen.ui.theme.ink

/**
 * Press desk (canvas direction 1c).
 *
 * Generation is a compose bar at the thumb; a finished run lands above it as
 * proof slips in two columns, triaged in place. The desk is empty until a run
 * exists, so the same screen carries both states.
 */
@Composable
fun GenerateScreen(
    onMessage: (String) -> Unit,
    vm: GenerateViewModel = viewModel(),
) {
    val state by vm.state.collectAsStateWithLifecycle()
    val keyboard = LocalSoftwareKeyboardController.current

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
                    "Install AnkiDroid from Google Play or F-Droid to send cards " +
                        "straight into your collection.",
                    style = MaterialTheme.typography.bodyMedium,
                )
            },
            confirmButton = {
                TextButton(onClick = vm::dismissAnkiDroidMissing) { Text("OK") }
            },
        )
    }

    Column(Modifier.fillMaxSize()) {
        if (state.hasResults) {
            RunHeader(state, vm)
            SlipGrid(state, vm, Modifier.weight(1f))
        } else {
            EmptyDesk(state, vm, Modifier.weight(1f))
        }

        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 12.dp),
        ) {
            if (state.hasResults) {
                PrimaryButton(
                    label = if (state.kept > 0) "Send ${state.kept} to AnkiDroid"
                    else "Nothing kept yet",
                    onClick = vm::sendToAnkiDroid,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = state.kept > 0,
                    loading = state.isSending,
                )
                Spacer(Modifier.height(8.dp))
                ComposeBar(
                    value = state.topic,
                    onValueChange = vm::onTopicChange,
                    onSubmit = {
                        keyboard?.hide()
                        vm.generate()
                    },
                    height = 40,
                    fontSize = 14,
                    enabled = state.canGenerate,
                    loading = state.isGenerating,
                    accent = false,
                )
            } else {
                TypeRow(
                    types = CardType.all,
                    labels = CardType::label,
                    selected = state.cardType,
                    onSelect = vm::onTypeChange,
                    modifier = Modifier.padding(bottom = 12.dp),
                    trailing = { CountPicker(state.count, vm::onCountChange) },
                )
                ComposeBar(
                    value = state.topic,
                    onValueChange = vm::onTopicChange,
                    onSubmit = {
                        keyboard?.hide()
                        vm.generate()
                    },
                    enabled = state.canGenerate,
                    loading = state.isGenerating,
                )
            }
        }
    }
}

@Composable
private fun EmptyDesk(
    state: GenerateUiState,
    vm: GenerateViewModel,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp)
            .padding(top = 14.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom,
        ) {
            Kicker("AnkiGen · Desk")
            Kicker("${state.totalOnServer} on server")
        }

        Spacer(Modifier.height(16.dp))
        Text(
            if (state.isGenerating) "Setting the run" else "Nothing on the desk",
            style = MaterialTheme.typography.titleLarge,
            color = Ink,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            if (state.isGenerating) {
                "Generating ${state.count} ${CardType.label(state.cardType).lowercase()} " +
                    "cards. The slips land here as soon as the model answers."
            } else {
                "Give it a topic and a run of cards lands here as proof slips. " +
                    "Mark what you keep, then send the lot to AnkiDroid."
            },
            style = MaterialTheme.typography.bodyMedium.copy(fontSize = 13.5.sp),
            color = ink(0.62f),
        )

        if (state.recentRuns.isNotEmpty()) {
            Spacer(Modifier.height(22.dp))
            Kicker("Recent runs")
            Spacer(Modifier.height(12.dp))
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                state.recentRuns.forEach { run ->
                    RunRow(
                        topic = run.topic,
                        detail = run.detail,
                        onClick = { vm.onTopicChange(run.topic) },
                    )
                }
            }
        }
    }
}

@Composable
private fun RunHeader(state: GenerateUiState, vm: GenerateViewModel) {
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
            Kicker(
                "${state.runTopic} · ${CardType.label(state.cardType)}",
                color = Cyan,
                modifier = Modifier.weight(1f, fill = false),
            )
            Kicker(
                if (state.waiting > 0) "Keep all" else "Clear",
                modifier = Modifier
                    .padding(start = 10.dp)
                    .clickable { if (state.waiting > 0) vm.keepAll() else vm.clearRun() },
                color = Cyan,
            )
        }

        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                "${state.results.size} slip${if (state.results.size == 1) "" else "s"}",
                style = MaterialTheme.typography.titleMedium.copy(
                    fontSize = 22.sp,
                    fontWeight = FontWeight.SemiBold,
                ),
                color = Ink,
            )
            Spacer(Modifier.width(8.dp))
            Kicker(state.tally, modifier = Modifier.padding(bottom = 2.dp))
        }
    }
}

@Composable
private fun SlipGrid(
    state: GenerateUiState,
    vm: GenerateViewModel,
    modifier: Modifier = Modifier,
) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(2),
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp),
        contentPadding = PaddingValues(top = 16.dp, bottom = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(state.results, key = { it.id }) { card ->
            Slip(
                kicker = CardType.label(card.cardType),
                question = card.frontText,
                answer = card.backText,
                state = slipStateOf(card),
                isDuplicate = card.status == CardStatus.DUPLICATE,
                onKeep = { vm.setStatus(card, CardStatus.ACCEPTED) },
                onDrop = { vm.setStatus(card, CardStatus.REJECTED) },
            )
        }
    }
}

private fun slipStateOf(card: Card): SlipState = when (card.status) {
    CardStatus.ACCEPTED, CardStatus.EXPORTED -> SlipState.Kept
    CardStatus.REJECTED, CardStatus.DUPLICATE -> SlipState.Dropped
    else -> SlipState.Waiting
}

@Composable
private fun CountPicker(count: Int, onChange: (Int) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Text(
        "$count ▾",
        style = MaterialTheme.typography.labelMedium,
        color = ink(0.45f),
        modifier = Modifier.clickable { expanded = true },
    )
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        listOf(1, 3, 5, 8, 10, 15, 20).forEach { n ->
            DropdownMenuItem(
                text = { Text("$n cards", style = MaterialTheme.typography.bodyMedium) },
                onClick = {
                    onChange(n)
                    expanded = false
                },
            )
        }
    }
}
