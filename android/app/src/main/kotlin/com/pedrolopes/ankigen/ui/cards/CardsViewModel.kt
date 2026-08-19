package com.pedrolopes.ankigen.ui.cards

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pedrolopes.ankigen.AnkiGenApplication
import com.pedrolopes.ankigen.data.anki.SendResult
import com.pedrolopes.ankigen.data.model.Card
import com.pedrolopes.ankigen.data.model.CardStatus
import com.pedrolopes.ankigen.data.model.imageFilename
import com.pedrolopes.ankigen.data.remote.toUserMessage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CardsUiState(
    val cards: List<Card> = emptyList(),
    val topics: List<String> = emptyList(),
    val statusFilter: String? = null,
    val topicFilter: String? = null,
    val typeFilter: String? = null,
    val selected: Set<Int> = emptySet(),
    val isLoading: Boolean = false,
    val isSending: Boolean = false,
    val error: String? = null,
    val message: String? = null,
    val needsPermission: Boolean = false,
    val ankiDroidMissing: Boolean = false,
)

class CardsViewModel(app: Application) : AndroidViewModel(app) {

    private val repo = getApplication<AnkiGenApplication>().repository
    private val ankiDroid = getApplication<AnkiGenApplication>().ankiDroid
    private val settings = getApplication<AnkiGenApplication>().settings

    private val _state = MutableStateFlow(CardsUiState())
    val state: StateFlow<CardsUiState> = _state.asStateFlow()

    init {
        refresh()
        loadTopics()
    }

    fun imageUrl(card: Card): String? = card.imageFilename?.let(repo::mediaUrl)

    fun dismissMessage() = _state.update { it.copy(message = null, error = null) }

    fun setStatusFilter(value: String?) {
        _state.update { it.copy(statusFilter = value) }
        refresh()
    }

    fun setTopicFilter(value: String?) {
        _state.update { it.copy(topicFilter = value) }
        refresh()
    }

    fun setTypeFilter(value: String?) {
        _state.update { it.copy(typeFilter = value) }
        refresh()
    }

    fun refresh() {
        val s = _state.value
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            repo.listCards(s.topicFilter, s.statusFilter, s.typeFilter)
                .onSuccess { cards ->
                    _state.update { st ->
                        // Drop selections for cards that no longer match the filter.
                        val visible = cards.map { it.id }.toSet()
                        st.copy(
                            isLoading = false,
                            cards = cards,
                            selected = st.selected intersect visible,
                        )
                    }
                }
                .onFailure { e ->
                    _state.update { it.copy(isLoading = false, error = e.toUserMessage()) }
                }
        }
    }

    private fun loadTopics() {
        viewModelScope.launch {
            repo.topics().onSuccess { topics -> _state.update { it.copy(topics = topics) } }
        }
    }

    fun toggleSelection(id: Int) = _state.update { st ->
        st.copy(selected = if (id in st.selected) st.selected - id else st.selected + id)
    }

    fun clearSelection() = _state.update { it.copy(selected = emptySet()) }

    fun selectAllVisible() = _state.update { st ->
        st.copy(selected = st.cards.map { it.id }.toSet())
    }

    fun setStatus(card: Card, status: String) {
        viewModelScope.launch {
            repo.setStatus(card.id, status)
                .onSuccess { refresh() }
                .onFailure { e -> _state.update { it.copy(error = e.toUserMessage()) } }
        }
    }

    fun bulkStatus(status: String) {
        val ids = _state.value.selected.toList()
        if (ids.isEmpty()) return
        viewModelScope.launch {
            repo.setStatusBatch(ids, status)
                .onSuccess { count ->
                    _state.update { it.copy(selected = emptySet(), message = "$count updated") }
                    refresh()
                }
                .onFailure { e -> _state.update { it.copy(error = e.toUserMessage()) } }
        }
    }

    fun delete(card: Card) {
        viewModelScope.launch {
            repo.deleteCard(card.id)
                .onSuccess {
                    _state.update { it.copy(selected = it.selected - card.id) }
                    refresh()
                }
                .onFailure { e -> _state.update { it.copy(error = e.toUserMessage()) } }
        }
    }

    /**
     * Sends the current selection to AnkiDroid, or every accepted card in view
     * when nothing is selected.
     */
    fun sendToAnkiDroid() {
        val s = _state.value
        val target = if (s.selected.isNotEmpty()) {
            s.cards.filter { it.id in s.selected }
        } else {
            s.cards.filter { it.status == CardStatus.ACCEPTED }
        }

        if (target.isEmpty()) {
            _state.update { it.copy(message = "Nothing to send — select cards or accept some first.") }
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
            when (val result = ankiDroid.send(target, settings.deckName)) {
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
                    _state.update {
                        it.copy(isSending = false, message = note, selected = emptySet())
                    }
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
}
