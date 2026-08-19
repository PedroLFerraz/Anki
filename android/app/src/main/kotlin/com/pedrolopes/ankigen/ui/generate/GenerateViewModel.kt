package com.pedrolopes.ankigen.ui.generate

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pedrolopes.ankigen.AnkiGenApplication
import com.pedrolopes.ankigen.data.anki.SendResult
import com.pedrolopes.ankigen.data.model.Card
import com.pedrolopes.ankigen.data.model.CardStatus
import com.pedrolopes.ankigen.data.model.CardType
import com.pedrolopes.ankigen.data.model.imageFilename
import com.pedrolopes.ankigen.data.remote.toUserMessage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class GenerateUiState(
    val topic: String = "",
    val cardType: String = CardType.BASIC,
    val count: Int = 5,
    val isGenerating: Boolean = false,
    val isSending: Boolean = false,
    val results: List<Card> = emptyList(),
    val error: String? = null,
    val message: String? = null,
    /** Set when AnkiDroid is missing or the permission has not been granted. */
    val needsPermission: Boolean = false,
    val ankiDroidMissing: Boolean = false,
) {
    val acceptedCount: Int get() = results.count { it.status == CardStatus.ACCEPTED }
    val pendingCount: Int get() = results.count { it.status == CardStatus.GENERATED }
    val canGenerate: Boolean get() = topic.isNotBlank() && !isGenerating && count > 0
}

class GenerateViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = getApplication<AnkiGenApplication>().repository
    private val ankiDroid = getApplication<AnkiGenApplication>().ankiDroid
    private val settings = getApplication<AnkiGenApplication>().settings

    private val _state = MutableStateFlow(GenerateUiState())
    val state: StateFlow<GenerateUiState> = _state.asStateFlow()

    fun onTopicChange(value: String) = _state.update { it.copy(topic = value) }
    fun onTypeChange(value: String) = _state.update { it.copy(cardType = value) }
    fun onCountChange(value: Int) = _state.update { it.copy(count = value.coerceIn(1, 20)) }

    fun dismissMessage() = _state.update { it.copy(message = null, error = null) }

    fun imageUrl(card: Card): String? = card.imageFilename?.let(repo::mediaUrl)

    fun generate() {
        val s = _state.value
        if (!s.canGenerate) return

        _state.update { it.copy(isGenerating = true, error = null, message = null, results = emptyList()) }

        viewModelScope.launch {
            repo.generate(s.topic.trim(), s.count, s.cardType)
                .onSuccess { cards ->
                    _state.update {
                        it.copy(
                            isGenerating = false,
                            results = cards,
                            message = if (cards.isEmpty()) "No cards came back." else null,
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isGenerating = false, error = e.toUserMessage()) }
                }
        }
    }

    fun setStatus(card: Card, status: String) {
        viewModelScope.launch {
            repo.setStatus(card.id, status)
                .onSuccess { updated -> replace(updated) }
                .onFailure { e -> _state.update { it.copy(error = e.toUserMessage()) } }
        }
    }

    fun acceptAll() = bulk(CardStatus.ACCEPTED)
    fun rejectAll() = bulk(CardStatus.REJECTED)

    private fun bulk(status: String) {
        val pending = _state.value.results.filter { it.status == CardStatus.GENERATED }
        if (pending.isEmpty()) return

        viewModelScope.launch {
            repo.setStatusBatch(pending.map { it.id }, status)
                .onSuccess {
                    _state.update { st ->
                        st.copy(
                            results = st.results.map { c ->
                                if (c.status == CardStatus.GENERATED) c.copy(status = status) else c
                            },
                        )
                    }
                }
                .onFailure { e -> _state.update { it.copy(error = e.toUserMessage()) } }
        }
    }

    /** Push every accepted card in this batch straight into AnkiDroid. */
    fun sendToAnkiDroid() {
        val accepted = _state.value.results.filter { it.status == CardStatus.ACCEPTED }
        if (accepted.isEmpty()) {
            _state.update { it.copy(message = "Accept some cards first.") }
            return
        }
        if (!ankiDroid.isAnkiDroidInstalled()) {
            _state.update { it.copy(ankiDroidMissing = true) }
            return
        }
        if (!ankiDroid.hasPermission()) {
            _state.update { it.copy(needsPermission = true) }
            return
        }

        _state.update { it.copy(isSending = true, error = null, message = null) }

        viewModelScope.launch {
            when (val result = ankiDroid.send(accepted, settings.deckName)) {
                is SendResult.Success -> {
                    val note = buildString {
                        append("Sent ${result.added} card")
                        if (result.added != 1) append("s")
                        append(" to AnkiDroid.")
                        if (result.imagesDropped > 0) {
                            append(" ${result.imagesDropped} image")
                            if (result.imagesDropped != 1) append("s")
                            append(" could not come along — see the README.")
                        }
                    }
                    _state.update { it.copy(isSending = false, message = note) }
                }
                SendResult.AnkiDroidNotInstalled ->
                    _state.update { it.copy(isSending = false, ankiDroidMissing = true) }
                SendResult.PermissionDenied ->
                    _state.update { it.copy(isSending = false, needsPermission = true) }
                is SendResult.Failed ->
                    _state.update { it.copy(isSending = false, error = result.message) }
            }
        }
    }

    fun onPermissionResult(granted: Boolean) {
        _state.update { it.copy(needsPermission = false) }
        if (granted) sendToAnkiDroid()
        else _state.update { it.copy(error = "AnkiDroid permission denied.") }
    }

    fun dismissAnkiDroidMissing() = _state.update { it.copy(ankiDroidMissing = false) }

    private fun replace(updated: Card) = _state.update { st ->
        st.copy(results = st.results.map { if (it.id == updated.id) updated else it })
    }
}
