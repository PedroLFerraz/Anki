package com.pedrolopes.ankigen.ui.generate

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pedrolopes.ankigen.data.anki.AnkiDroidExporter
import com.pedrolopes.ankigen.data.model.CardStatus
import com.pedrolopes.ankigen.data.model.CardType
import com.pedrolopes.ankigen.ui.components.CardItem

@OptIn(ExperimentalMaterial3Api::class)
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
            title = { Text("AnkiDroid not found") },
            text = {
                Text(
                    "Install AnkiDroid from Google Play or F-Droid to send cards " +
                        "straight into your collection. Until then you can still " +
                        "export an .apkg from the web interface.",
                )
            },
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

        OutlinedTextField(
            value = state.topic,
            onValueChange = vm::onTopicChange,
            label = { Text("Topic") },
            placeholder = { Text("e.g. Krebs cycle, Roman Republic") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
            keyboardActions = KeyboardActions(onGo = {
                keyboard?.hide()
                vm.generate()
            }),
        )

        Spacer(Modifier.height(10.dp))

        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            CardType.all.forEach { type ->
                FilterChip(
                    selected = state.cardType == type,
                    onClick = { vm.onTypeChange(type) },
                    label = { Text(CardType.label(type)) },
                )
            }
        }

        Spacer(Modifier.height(10.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            CountPicker(state.count, vm::onCountChange)
            Spacer(Modifier.weight(1f))
            Button(
                onClick = {
                    keyboard?.hide()
                    vm.generate()
                },
                enabled = state.canGenerate,
            ) {
                if (state.isGenerating) {
                    CircularProgressIndicator(
                        Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.size(8.dp))
                    Text("Generating...")
                } else {
                    Text("Generate")
                }
            }
        }

        Spacer(Modifier.height(12.dp))

        if (state.results.isNotEmpty()) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(
                    "${state.results.size} generated",
                    style = MaterialTheme.typography.titleMedium,
                )
                Spacer(Modifier.weight(1f))
                if (state.pendingCount > 0) {
                    TextButton(onClick = vm::rejectAll) { Text("Reject all") }
                    TextButton(onClick = vm::acceptAll) { Text("Accept all") }
                }
            }

            if (state.acceptedCount > 0) {
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
                        Text("Send ${state.acceptedCount} to AnkiDroid")
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
        }

        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(state.results, key = { it.id }) { card ->
                CardItem(
                    card = card,
                    imageUrl = vm.imageUrl(card),
                    onAccept = if (card.status == CardStatus.GENERATED) {
                        { vm.setStatus(card, CardStatus.ACCEPTED) }
                    } else null,
                    onReject = if (card.status == CardStatus.GENERATED) {
                        { vm.setStatus(card, CardStatus.REJECTED) }
                    } else null,
                )
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun CountPicker(count: Int, onChange: (Int) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    OutlinedButton(onClick = { expanded = true }) {
        Text("$count cards")
        Icon(Icons.Default.ArrowDropDown, contentDescription = null)
    }
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        listOf(1, 3, 5, 8, 10, 15, 20).forEach { n ->
            DropdownMenuItem(
                text = { Text("$n cards") },
                onClick = {
                    onChange(n)
                    expanded = false
                },
            )
        }
    }
}
