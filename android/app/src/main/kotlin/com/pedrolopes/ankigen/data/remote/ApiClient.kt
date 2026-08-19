package com.pedrolopes.ankigen.data.remote

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import com.pedrolopes.ankigen.data.model.ApiError
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.HttpException
import retrofit2.Retrofit
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit

object ApiClient {

    val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
    }

    private var cachedBaseUrl: String? = null
    private var cached: AnkiGenApi? = null

    /**
     * Retrofit pins its base URL at build time but ours is user-configurable,
     * so rebuild whenever it changes. Cheap — this happens once per URL.
     */
    @Synchronized
    fun forBaseUrl(baseUrl: String): AnkiGenApi {
        val normalized = normalize(baseUrl)
        cached?.let { if (normalized == cachedBaseUrl) return it }

        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }

        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
            .connectTimeout(15, TimeUnit.SECONDS)
            // Generation runs a local LLM and can download images afterwards;
            // a request routinely takes minutes, so the read timeout is generous.
            .readTimeout(10, TimeUnit.MINUTES)
            .writeTimeout(1, TimeUnit.MINUTES)
            .retryOnConnectionFailure(true)
            .build()

        val api = Retrofit.Builder()
            .baseUrl(normalized)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(AnkiGenApi::class.java)

        cachedBaseUrl = normalized
        cached = api
        return api
    }

    /** Retrofit demands a trailing slash and a scheme. */
    fun normalize(raw: String): String {
        var url = raw.trim()
        if (url.isEmpty()) url = "http://10.0.2.2:8000"
        if (!url.startsWith("http://") && !url.startsWith("https://")) url = "http://$url"
        if (!url.endsWith("/")) url = "$url/"
        return url
    }
}

/** Turns transport and HTTP failures into something worth showing a user. */
fun Throwable.toUserMessage(): String = when (this) {
    is SocketTimeoutException ->
        "Timed out. The model may still be generating — try a smaller count."
    is HttpException -> {
        val body = runCatching { response()?.errorBody()?.string() }.getOrNull()
        val detail = body?.let {
            runCatching { ApiClient.json.decodeFromString<ApiError>(it).message }.getOrNull()
        }
        detail ?: "Server error ${code()}"
    }
    is IOException ->
        "Can't reach the server. Check the URL in Settings and that it's running."
    else -> message ?: "Something went wrong"
}
