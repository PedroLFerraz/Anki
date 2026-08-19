package com.pedrolopes.ankigen.ui.settings

import android.app.Application
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pedrolopes.ankigen.AnkiGenApplication
import com.pedrolopes.ankigen.data.local.SettingsStore
import com.pedrolopes.ankigen.data.remote.toUserMessage
import com.pedrolopes.ankigen.ui.theme.StatusGreen
import com.pedrolopes.ankigen.ui.theme.StatusRed
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val serverUrl: String = "",
    val deckName: String = "",
    val isTesting: Boolean = false,
    val testResult: String? = null,
    val testOk: Boolean = false,
    val ankiDroidInstalled: Boolean = false,
    val totalCards: Int = 0,
    val byStatus: Map<String, Int> = emptyMap(),
)

class SettingsViewModel(app: Application) : AndroidViewModel(app) {

    private val settings = getApplication<AnkiGenApplication>().settings
    private val repo = getApplication<AnkiGenApplication>().repository
    private val ankiDroid = getApplication<AnkiGenApplication>().ankiDroid

    private val _state = MutableStateFlow(
        SettingsUiState(
            serverUrl = settings.serverUrl,
            deckName = settings.deckName,
            ankiDroidInstalled = ankiDroid.isAnkiDroidInstalled(),
        ),
    )
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    fun onUrlChange(value: String) {
        settings.serverUrl = value
        _state.update { it.copy(serverUrl = value, testResult = null) }
    }

    fun onDeckNameChange(value: String) {
        // The cached AnkiDroid deck ID belongs to the old name.
        if (value.trim() != settings.deckName) settings.clearDeckId()
        settings.deckName = value
        _state.update { it.copy(deckName = value) }
    }

    fun testConnection() {
        _state.update { it.copy(isTesting = true, testResult = null) }
        viewModelScope.launch {
            repo.health()
                .onSuccess { llmError ->
                    _state.update {
                        it.copy(
                            isTesting = false,
                            testOk = llmError == null,
                            testResult = llmError ?: "Connected. LLM is reachable.",
                        )
                    }
                }
                .onFailure { e ->
                    _state.update {
                        it.copy(isTesting = false, testOk = false, testResult = e.toUserMessage())
                    }
                }
            refreshCounts()
        }
    }

    fun refreshCounts() {
        viewModelScope.launch {
            repo.counts().onSuccess { counts ->
                _state.update {
                    it.copy(totalCards = counts.total, byStatus = counts.byStatus)
                }
            }
        }
    }

    fun refreshAnkiDroid() = _state.update {
        it.copy(ankiDroidInstalled = ankiDroid.isAnkiDroidInstalled())
    }
}

@Composable
fun SettingsScreen(vm: SettingsViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) {
        vm.refreshAnkiDroid()
        vm.refreshCounts()
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {

        Text("Backend", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))

        OutlinedTextField(
            value = state.serverUrl,
            onValueChange = vm::onUrlChange,
            label = { Text("Server URL") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(4.dp))
        Text(
            "Use ${SettingsStore.DEFAULT_SERVER_URL} on the emulator, or your PC's " +
                "LAN address (e.g. http://192.168.1.42:8000) on a real device. " +
                "Start the backend with --host 0.0.0.0 so it accepts connections " +
                "from the phone.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(10.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = vm::testConnection, enabled = !state.isTesting) {
                if (state.isTesting) {
                    CircularProgressIndicator(
                        Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.size(8.dp))
                    Text("Testing...")
                } else {
                    Text("Test connection")
                }
            }
            Spacer(Modifier.size(12.dp))
            state.testResult?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (state.testOk) StatusGreen else StatusRed,
                )
            }
        }

        Spacer(Modifier.height(20.dp))
        HorizontalDivider()
        Spacer(Modifier.height(20.dp))

        Text("AnkiDroid", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))

        OutlinedTextField(
            value = state.deckName,
            onValueChange = vm::onDeckNameChange,
            label = { Text("Target deck") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))

        Card(
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
            ),
        ) {
            Column(Modifier.padding(12.dp)) {
                Text(
                    if (state.ankiDroidInstalled) "AnkiDroid detected"
                    else "AnkiDroid not installed",
                    color = if (state.ankiDroidInstalled) StatusGreen else StatusRed,
                    style = MaterialTheme.typography.bodyLarge,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    if (state.ankiDroidInstalled) {
                        "Cards are written straight into your collection — no .apkg " +
                            "import needed. Images stay behind for now; detailed cards " +
                            "keep their text and visual cards fall back to title plus " +
                            "explanation."
                    } else {
                        "Install AnkiDroid from Google Play or F-Droid to send cards " +
                            "directly. Without it, export an .apkg from the web interface."
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Spacer(Modifier.height(20.dp))
        HorizontalDivider()
        Spacer(Modifier.height(20.dp))

        Text("Collection", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        Text(
            "${state.totalCards} cards on the server",
            style = MaterialTheme.typography.bodyLarge,
        )
        Spacer(Modifier.height(4.dp))
        state.byStatus.entries.sortedBy { it.key }.forEach { (status, count) ->
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    status,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontFamily = FontFamily.Monospace,
                )
                Text("$count", style = MaterialTheme.typography.bodyMedium)
            }
        }

        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = vm::refreshCounts) { Text("Refresh") }

        Spacer(Modifier.height(32.dp))
    }
}
