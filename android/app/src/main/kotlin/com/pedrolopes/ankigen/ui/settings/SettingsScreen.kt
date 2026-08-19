package com.pedrolopes.ankigen.ui.settings

import android.app.Application
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.pedrolopes.ankigen.AnkiGenApplication
import com.pedrolopes.ankigen.data.local.SettingsStore
import com.pedrolopes.ankigen.data.remote.toUserMessage
import com.pedrolopes.ankigen.ui.components.Kicker
import com.pedrolopes.ankigen.ui.components.SecondaryButton
import com.pedrolopes.ankigen.ui.theme.Cyan
import com.pedrolopes.ankigen.ui.theme.Cyan700
import com.pedrolopes.ankigen.ui.theme.Divider
import com.pedrolopes.ankigen.ui.theme.Ink
import com.pedrolopes.ankigen.ui.theme.Magenta700
import com.pedrolopes.ankigen.ui.theme.SourceSerif4
import com.pedrolopes.ankigen.ui.theme.ink
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
        // The cached AnkiDroid deck id belongs to the old name.
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
                            testResult = llmError ?: "Connected. The model answers.",
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
                _state.update { it.copy(totalCards = counts.total, byStatus = counts.byStatus) }
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
            .padding(horizontal = 20.dp)
            .padding(top = 14.dp),
    ) {
        Kicker("AnkiGen · Settings")
        Spacer(Modifier.height(16.dp))

        SectionTitle("Backend")
        RuledField(
            label = "Server URL",
            value = state.serverUrl,
            onValueChange = vm::onUrlChange,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "Use ${SettingsStore.DEFAULT_SERVER_URL} on the emulator, or your machine's " +
                "LAN address on a real device. Start the backend with --host 0.0.0.0 so it " +
                "accepts connections from the phone.",
            style = MaterialTheme.typography.bodyMedium,
            color = ink(0.62f),
        )
        Spacer(Modifier.height(14.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            SecondaryButton(
                if (state.isTesting) "Testing..." else "Test connection",
                vm::testConnection,
                height = 40, fontSize = 14, color = Cyan700,
            )
            Spacer(Modifier.width(12.dp))
            state.testResult?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodyMedium.copy(fontSize = 12.5.sp),
                    color = if (state.testOk) Cyan700 else Magenta700,
                )
            }
        }

        SectionRule()

        SectionTitle("AnkiDroid")
        RuledField(
            label = "Target deck",
            value = state.deckName,
            onValueChange = vm::onDeckNameChange,
        )
        Spacer(Modifier.height(12.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(2.dp))
                .padding(12.dp),
        ) {
            Column {
                Text(
                    if (state.ankiDroidInstalled) "AnkiDroid detected" else "AnkiDroid not installed",
                    style = MaterialTheme.typography.labelLarge,
                    color = if (state.ankiDroidInstalled) Cyan700 else Magenta700,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    if (state.ankiDroidInstalled) {
                        "Cards are written straight into your collection — no .apkg import. " +
                            "Images stay behind for now; detailed cards keep their text and " +
                            "visual cards fall back to title plus explanation."
                    } else {
                        "Install AnkiDroid from Google Play or F-Droid to send cards directly. " +
                            "Without it, export an .apkg from the web interface."
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = ink(0.62f),
                )
            }
        }

        SectionRule()

        SectionTitle("Collection")
        Text(
            "${state.totalCards} on server",
            style = MaterialTheme.typography.titleMedium.copy(fontSize = 22.sp),
            color = Ink,
        )
        Spacer(Modifier.height(10.dp))
        state.byStatus.entries.sortedByDescending { it.value }.forEach { (status, count) ->
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(vertical = 3.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Bottom,
            ) {
                Kicker(status)
                Text(
                    "$count",
                    style = MaterialTheme.typography.labelMedium,
                    color = Ink,
                )
            }
        }
        Spacer(Modifier.height(14.dp))
        SecondaryButton("Refresh", vm::refreshCounts, height = 40, fontSize = 14, color = Cyan700)

        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        color = Ink,
        modifier = Modifier.padding(bottom = 10.dp),
    )
}

@Composable
private fun SectionRule() {
    Spacer(Modifier.height(20.dp))
    HorizontalDivider(color = Divider)
    Spacer(Modifier.height(20.dp))
}

/**
 * Broadsheet has no filled input on a settings page — the value sits on the
 * paper under a hairline rule, labelled by a kicker.
 */
@Composable
private fun RuledField(label: String, value: String, onValueChange: (String) -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Kicker(label)
        Spacer(Modifier.height(4.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .border(1.dp, Divider, RoundedCornerShape(2.dp))
                .padding(horizontal = 10.dp, vertical = 10.dp),
        ) {
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = true,
                textStyle = LocalTextStyle.current.copy(
                    fontFamily = SourceSerif4,
                    fontSize = 14.sp,
                    color = Ink,
                ),
                cursorBrush = SolidColor(Cyan),
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}
