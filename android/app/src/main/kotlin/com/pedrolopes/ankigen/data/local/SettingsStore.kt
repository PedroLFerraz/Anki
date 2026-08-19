package com.pedrolopes.ankigen.data.local

import android.content.Context
import androidx.core.content.edit

/**
 * A handful of scalar settings. SharedPreferences rather than DataStore on
 * purpose: everything here is read synchronously during composition and the
 * coroutine plumbing DataStore needs would not buy anything at this size.
 */
class SettingsStore(context: Context) {

    private val prefs = context.getSharedPreferences("ankigen_settings", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL
        set(value) = prefs.edit { putString(KEY_SERVER_URL, value.trim()) }

    var deckName: String
        get() = prefs.getString(KEY_DECK_NAME, DEFAULT_DECK) ?: DEFAULT_DECK
        set(value) = prefs.edit { putString(KEY_DECK_NAME, value.trim()) }

    /**
     * AnkiDroid assigns its own model IDs, so the ID it handed back for each
     * card type is cached here and reused — otherwise every send would create
     * another duplicate note type in the user's collection.
     */
    fun modelId(cardType: String): Long? =
        prefs.getLong(modelKey(cardType), -1L).takeIf { it > 0 }

    fun setModelId(cardType: String, id: Long) =
        prefs.edit { putLong(modelKey(cardType), id) }

    fun deckId(): Long? = prefs.getLong(KEY_DECK_ID, -1L).takeIf { it > 0 }

    fun setDeckId(id: Long) = prefs.edit { putLong(KEY_DECK_ID, id) }

    /** Deck IDs are per-deck-name; changing the name must not reuse the old ID. */
    fun clearDeckId() = prefs.edit { remove(KEY_DECK_ID) }

    private fun modelKey(cardType: String) = "model_id_$cardType"

    companion object {
        // 10.0.2.2 is the host machine as seen from the Android emulator.
        const val DEFAULT_SERVER_URL = "http://10.0.2.2:8000"
        const val DEFAULT_DECK = "AnkiGen"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_DECK_NAME = "deck_name"
        private const val KEY_DECK_ID = "deck_id"
    }
}
