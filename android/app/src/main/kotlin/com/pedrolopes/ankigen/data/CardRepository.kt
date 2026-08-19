package com.pedrolopes.ankigen.data

import com.pedrolopes.ankigen.data.local.SettingsStore
import com.pedrolopes.ankigen.data.model.BatchStatusUpdate
import com.pedrolopes.ankigen.data.model.Card
import com.pedrolopes.ankigen.data.model.CountsResponse
import com.pedrolopes.ankigen.data.model.GenerateRequest
import com.pedrolopes.ankigen.data.model.StatusUpdate
import com.pedrolopes.ankigen.data.remote.AnkiGenApi
import com.pedrolopes.ankigen.data.remote.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Single entry point to the backend. Resolves the Retrofit instance per call so
 * a server URL edited in Settings takes effect without an app restart.
 */
class CardRepository(private val settings: SettingsStore) {

    private val api: AnkiGenApi
        get() = ApiClient.forBaseUrl(settings.serverUrl)

    /** Base URL for resolving `/media/<file>` image references. */
    fun mediaUrl(filename: String): String =
        ApiClient.normalize(settings.serverUrl) + "media/" + filename

    suspend fun health(): Result<String?> = call {
        api.health().let { if (it.status == "ok") null else it.error ?: "LLM unavailable" }
    }

    suspend fun generate(
        topic: String,
        count: Int,
        cardType: String,
        noEmbeddings: Boolean = false,
    ): Result<List<Card>> = call {
        api.generate(GenerateRequest(topic, count, cardType, noEmbeddings)).cards
    }

    suspend fun listCards(
        topic: String? = null,
        status: String? = null,
        cardType: String? = null,
    ): Result<List<Card>> = call {
        api.listCards(topic, status, cardType).cards.filter { it.status != "CONTEXT" }
    }

    suspend fun setStatus(id: Int, status: String): Result<Card> = call {
        api.updateStatus(id, StatusUpdate(status))
    }

    suspend fun setStatusBatch(ids: List<Int>, status: String): Result<Int> = call {
        if (ids.isEmpty()) 0 else api.batchStatus(BatchStatusUpdate(ids, status)).updated
    }

    suspend fun deleteCard(id: Int): Result<Unit> = call {
        api.deleteCard(id)
        Unit
    }

    suspend fun topics(): Result<List<String>> = call { api.topics().topics }

    suspend fun counts(): Result<CountsResponse> = call { api.counts() }

    suspend fun clear(statuses: String): Result<Int> = call {
        api.clear(statuses).deleted
    }

    private suspend fun <T> call(block: suspend () -> T): Result<T> =
        withContext(Dispatchers.IO) {
            runCatching { block() }
        }
}
