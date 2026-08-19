package com.pedrolopes.ankigen.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * Mirrors a row from the Python side's `cards` table as returned by
 * `repository.get_cards()` / `get_card_by_id()`.
 */
@Serializable
data class Card(
    val id: Int,
    val question: String = "",
    val answer: String = "",
    val topic: String? = null,
    val status: String = "GENERATED",
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("card_type") val cardType: String = "basic",
    @SerialName("extra_fields") val extraFields: JsonObject? = null,
)

/**
 * `extra_fields` is a free-form dict on the server, so read it defensively —
 * a non-string value must not blow up the whole response.
 */
fun Card.extra(key: String): String? =
    (extraFields?.get(key) as? JsonPrimitive)?.contentOrNull

val Card.imageFilename: String? get() = extra("image_filename")

/** The text that belongs on the front of the card, per card type. */
val Card.frontText: String
    get() = when (cardType) {
        "visual" -> extra("title") ?: question
        "cloze" -> maskCloze(extra("text") ?: answer)
        else -> question
    }

/** The text that belongs on the back of the card, per card type. */
val Card.backText: String
    get() = when (cardType) {
        "visual" -> extra("explanation") ?: answer
        "cloze" -> stripCloze(extra("text") ?: answer)
        "detailed" -> listOfNotNull(
            extra("summary")?.takeIf { it.isNotBlank() } ?: answer,
            extra("explanation")?.takeIf { it.isNotBlank() },
        ).joinToString("\n\n")
        else -> answer
    }

private val CLOZE_RE = Regex("""\{\{c\d+::(.*?)(?:::.*?)?\}\}""")

/** `The {{c1::mitochondria}} is …` -> `The [...] is …` */
fun maskCloze(text: String): String = CLOZE_RE.replace(text) { "[...]" }

/** `The {{c1::mitochondria}} is …` -> `The mitochondria is …` */
fun stripCloze(text: String): String = CLOZE_RE.replace(text) { it.groupValues[1] }

@Serializable
data class CardsResponse(val cards: List<Card> = emptyList())

@Serializable
data class GenerateRequest(
    val topic: String,
    val count: Int,
    @SerialName("card_type") val cardType: String,
    @SerialName("no_embeddings") val noEmbeddings: Boolean = false,
)

@Serializable
data class StatusUpdate(val status: String)

@Serializable
data class BatchStatusUpdate(val ids: List<Int>, val status: String)

@Serializable
data class BatchStatusResponse(val updated: Int = 0)

@Serializable
data class CardUpdate(
    val question: String,
    val answer: String,
    @SerialName("extra_fields") val extraFields: Map<String, String>? = null,
)

@Serializable
data class CountsResponse(
    val total: Int = 0,
    @SerialName("by_status") val byStatus: Map<String, Int> = emptyMap(),
    @SerialName("by_type") val byType: Map<String, Int> = emptyMap(),
)

@Serializable
data class TopicsResponse(val topics: List<String> = emptyList())

@Serializable
data class HealthResponse(val status: String, val error: String? = null)

@Serializable
data class ClearResponse(val deleted: Int = 0)

@Serializable
data class OkResponse(val ok: Boolean = false)

/** FastAPI reports errors as `{"detail": "..."}`. */
@Serializable
data class ApiError(val detail: JsonElement? = null) {
    val message: String?
        get() = (detail as? JsonPrimitive)?.contentOrNull ?: detail?.toString()
}

object CardStatus {
    const val GENERATED = "GENERATED"
    const val ACCEPTED = "ACCEPTED"
    const val REJECTED = "REJECTED"
    const val DUPLICATE = "DUPLICATE"
    const val EXPORTED = "EXPORTED"
    const val CONTEXT = "CONTEXT"

    val selectable = listOf(GENERATED, ACCEPTED, REJECTED, DUPLICATE, EXPORTED)
}

object CardType {
    const val BASIC = "basic"
    const val DETAILED = "detailed"
    const val VISUAL = "visual"
    const val CLOZE = "cloze"

    val all = listOf(BASIC, DETAILED, VISUAL, CLOZE)

    fun label(type: String) = when (type) {
        BASIC -> "Basic"
        DETAILED -> "Detailed"
        VISUAL -> "Visual"
        CLOZE -> "Cloze"
        else -> type.replaceFirstChar { it.uppercase() }
    }
}
