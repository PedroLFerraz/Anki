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

/** A past generation run, summarised for the desk's "Recent runs" list. */
data class RecentRun(
    val topic: String,
    val kept: Int,
    val cardType: String,
) {
    val detail: String get() = "$kept kept · $cardType"
}

data class GenerateUiState(
    val topic: String = "",
    val cardType: String = CardType.BASIC,
    val count: Int = 5,
    val isGenerating: Boolean = false,
    val isSending: Boolean = false,
    val results: List<Card> = emptyList(),
    val recentRuns: List<RecentRun> = emptyList(),
    val totalOnServer: Int = 0,
    val runTopic: String = "",
    val error: String? = null,
    val message: String? = null,
    val needsPermission: Boolean = false,
    val ankiDroidMissing: Boolean = false,
) {
    val kept: Int get() = results.count { it.status == CardStatus.ACCEPTED }
    val dropped: Int get() = results.count { it.status == CardStatus.REJECTED }
    val waiting: Int get() = results.count { it.status == CardStatus.GENERATED }
    val duplicates: Int get() = results.count { it.status == CardStatus.DUPLICATE }
    val hasResults: Boolean get() = results.isNotEmpty()
    val canGenerate: Boolean get() = topic.isNotBlank() && !isGenerating && count > 0

    /** "2 kept · 1 dropped · 2 waiting" — only the non-zero parts. */
    val tally: String
        get() = buildList {
            if (kept > 0) add("$kept kept")
            if (dropped > 0) add("$dropped dropped")
            if (duplicates > 0) add("$duplicates duplicate")
            if (waiting > 0) add("$waiting waiting")
        }.joinToString(" · ")
}

class GenerateViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = getApplication<AnkiGenApplication>().repository
    private val ankiDroid = getApplication<AnkiGenApplication>().ankiDroid
    private val settings = getApplication<AnkiGenApplication>().settings

    private val _state = MutableStateFlow(GenerateUiState())
    val state: StateFlow<GenerateUiState> = _state.asStateFlow()

    init {
        loadDesk()
    }

    fun onTopicChange(value: String) = _state.update { it.copy(topic = value) }
    fun onTypeChange(value: String) = _state.update { it.copy(cardType = value) }
    fun onCountChange(value: Int) = _state.update { it.copy(count = value.coerceIn(1, 20)) }

    fun dismissMessage() = _state.update { it.copy(message = null, error = null) }

    fun imageUrl(card: Card): String? = card.imageFilename?.let(repo::mediaUrl)

    /** Clears the current run and returns to the empty desk. */
    fun clearRun() = _state.update { it.copy(results = emptyList(), runTopic = "") }

    /**
     * The backend has no notion of a "run", so recent ones are reconstructed
     * by grouping cards by topic — newest first, by highest card id.
     */
    fun loadDesk() {
        viewModelScope.launch {
            repo.counts().onSuccess { counts ->
                _state.update { it.copy(totalOnServer = counts.total) }
            }
            repo.listCards().onSuccess { cards ->
                val runs = cards
                    .filter { !it.topic.isNullOrBlank() }
                    .groupBy { it.topic!! }
                    .map { (topic, group) ->
                        val kept = group.count {
                            it.status == CardStatus.ACCEPTED || it.status == CardStatus.EXPORTED
                        }
                        val dominant = group.groupingBy { it.cardType }.eachCount()
                            .maxByOrNull { e -> e.value }?.key ?: CardType.BASIC
                        RecentRun(topic, kept, dominant) to (group.maxOfOrNull { it.id } ?: 0)
                    }
                    .sortedByDescending { it.second }
                    .map { it.first }
                    .take(4)
                _state.update { it.copy(recentRuns = runs) }
            }
        }
    }

    fun generate() {
        val s = _state.value
        if (!s.canGenerate) return

        _state.update {
            it.copy(
                isGenerating = true, error = null, message = null,
                results = emptyList(), runTopic = s.topic.trim(),
            )
        }

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
                    loadDesk()
                }
                .onFailure { e ->
                    _state.update { it.copy(isGenerating = false, error = e.toUserMessage()) }
                }
        }
    }

    fun setStatus(card: Card, status: String) {
        // Update optimistically: triage should feel immediate under the thumb.
        replace(card.copy(status = status))
        viewModelScope.launch {
            repo.setStatus(card.id, status)
                .onSuccess { replace(it) }
                .onFailure { e ->
                    replace(card)
                    _state.update { it.copy(error = e.toUserMessage()) }
                }
        }
    }

    fun keepAll() {
        val waiting = _state.value.results.filter { it.status == CardStatus.GENERATED }
        if (waiting.isEmpty()) return

        _state.update { st ->
            st.copy(results = st.results.map {
                if (it.status == CardStatus.GENERATED) it.copy(status = CardStatus.ACCEPTED) else it
            })
        }
        viewModelScope.launch {
            repo.setStatusBatch(waiting.map { it.id }, CardStatus.ACCEPTED)
                .onFailure { e -> _state.update { it.copy(error = e.toUserMessage()) } }
        }
    }

    /** Push every kept card in this run into AnkiDroid. */
    fun sendToAnkiDroid() {
        val accepted = _state.value.results.filter { it.status == CardStatus.ACCEPTED }
        if (accepted.isEmpty()) {
            _state.update { it.copy(message = "Keep some cards first.") }
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
                            append(" could not come along.")
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
