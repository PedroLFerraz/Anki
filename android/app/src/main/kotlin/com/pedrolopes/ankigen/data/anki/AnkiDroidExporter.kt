package com.pedrolopes.ankigen.data.anki

import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import com.ichi2.anki.api.AddContentApi
import com.pedrolopes.ankigen.data.local.SettingsStore
import com.pedrolopes.ankigen.data.model.Card
import com.pedrolopes.ankigen.data.model.CardType
import com.pedrolopes.ankigen.data.model.backText
import com.pedrolopes.ankigen.data.model.frontText
import com.pedrolopes.ankigen.data.model.imageFilename

/** Outcome of pushing a batch of cards into AnkiDroid. */
sealed interface SendResult {
    data class Success(
        val added: Int,
        /** Cards whose image could not come along — see [AnkiDroidExporter]. */
        val imagesDropped: Int,
    ) : SendResult

    data object AnkiDroidNotInstalled : SendResult
    data object PermissionDenied : SendResult
    data class Failed(val message: String) : SendResult
}

/**
 * Writes notes directly into the user's AnkiDroid collection via
 * [AddContentApi], which removes the .apkg export/import round trip entirely.
 *
 * Two deliberate limitations in this version:
 *
 *  - **Media is not transferred.** Images live on the backend's filesystem and
 *    the note is created with its text fields only. Detailed cards survive this
 *    fine; visual cards degrade to title + explanation. [SendResult.Success]
 *    reports how many were affected so the UI can say so.
 *
 *  - **Cloze notes use a standard model.** `addNewCustomModel` cannot set a
 *    note type's cloze flag, so cloze cards are sent as a two-field note with
 *    the blanks masked on the front and revealed on the back. Functionally
 *    equivalent for review; it just is not a native Anki cloze note.
 */
class AnkiDroidExporter(
    private val context: Context,
    private val settings: SettingsStore,
) {

    private val api: AddContentApi by lazy { AddContentApi(context) }

    fun isAnkiDroidInstalled(): Boolean =
        AddContentApi.getAnkiDroidPackageName(context) != null

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, READ_WRITE_PERMISSION) ==
            PackageManager.PERMISSION_GRANTED

    fun send(cards: List<Card>, deckName: String): SendResult {
        if (cards.isEmpty()) return SendResult.Success(0, 0)
        if (!isAnkiDroidInstalled()) return SendResult.AnkiDroidNotInstalled
        if (!hasPermission()) return SendResult.PermissionDenied

        return try {
            val deckId = resolveDeckId(deckName)
                ?: return SendResult.Failed("Could not create the deck \"$deckName\" in AnkiDroid.")

            var added = 0
            var imagesDropped = 0

            // Group by card type: each type maps to its own AnkiDroid note type.
            for ((cardType, group) in cards.groupBy { it.cardType }) {
                val modelId = resolveModelId(cardType, deckId)
                    ?: return SendResult.Failed("Could not create the \"$cardType\" note type in AnkiDroid.")

                val fieldsList = group.map { card ->
                    if (card.imageFilename != null) imagesDropped++
                    arrayOf(card.frontText, card.backText)
                }
                val tagsList = group.map { card ->
                    setOfNotNull("ankigen", card.topic?.takeIf { it.isNotBlank() }?.let(::sanitizeTag))
                }

                added += api.addNotes(modelId, deckId, fieldsList, tagsList)
            }

            SendResult.Success(added, imagesDropped)
        } catch (e: SecurityException) {
            SendResult.PermissionDenied
        } catch (e: Exception) {
            SendResult.Failed(e.message ?: "AnkiDroid rejected the notes.")
        }
    }

    private fun resolveDeckId(deckName: String): Long? {
        settings.deckId()?.let { cached ->
            // Trust the cached ID only while the deck still exists under this name.
            val existing = runCatching { api.deckList }.getOrNull()
            if (existing?.get(cached) == deckName) return cached
        }
        val existingId = runCatching { api.deckList }.getOrNull()
            ?.entries?.firstOrNull { it.value == deckName }?.key
        val id = existingId ?: api.addNewDeck(deckName)
        id?.let(settings::setDeckId)
        return id
    }

    private fun resolveModelId(cardType: String, deckId: Long): Long? {
        settings.modelId(cardType)?.let { cached ->
            val existing = runCatching { api.modelList }.getOrNull()
            if (existing?.containsKey(cached) == true) return cached
        }
        val name = modelName(cardType)
        val existingId = runCatching { api.modelList }.getOrNull()
            ?.entries?.firstOrNull { it.value == name }?.key
        val id = existingId ?: api.addNewCustomModel(
            name,
            FIELDS,
            CARD_NAMES,
            arrayOf(QFMT),
            arrayOf(AFMT),
            css(cardType),
            deckId,
            0,
        )
        id?.let { settings.setModelId(cardType, it) }
        return id
    }

    private fun modelName(cardType: String) = "AnkiGen ${CardType.label(cardType)}"

    /** Anki tags cannot contain spaces. */
    private fun sanitizeTag(raw: String) = raw.trim().replace(Regex("""\s+"""), "_")

    private fun css(cardType: String): String {
        val accent = if (cardType == CardType.CLOZE) "#66bb6a" else "#4fc3f7"
        return """
            .card {
              font-family: sans-serif;
              font-size: 20px;
              text-align: center;
              color: #e0e0e0;
              background-color: #1a1a2e;
              line-height: 1.6;
              padding: 16px;
            }
            .answer { color: $accent; }
        """.trimIndent()
    }

    companion object {
        val READ_WRITE_PERMISSION: String = AddContentApi.READ_WRITE_PERMISSION

        private val FIELDS = arrayOf("Front", "Back")
        private val CARD_NAMES = arrayOf("Card 1")
        private const val QFMT = "{{Front}}"
        private const val AFMT = "{{FrontSide}}<hr id=answer><div class=answer>{{Back}}</div>"
    }
}
