package com.pedrolopes.ankigen.data.remote

import com.pedrolopes.ankigen.data.model.BatchStatusResponse
import com.pedrolopes.ankigen.data.model.BatchStatusUpdate
import com.pedrolopes.ankigen.data.model.Card
import com.pedrolopes.ankigen.data.model.CardUpdate
import com.pedrolopes.ankigen.data.model.CardsResponse
import com.pedrolopes.ankigen.data.model.ClearResponse
import com.pedrolopes.ankigen.data.model.CountsResponse
import com.pedrolopes.ankigen.data.model.GenerateRequest
import com.pedrolopes.ankigen.data.model.HealthResponse
import com.pedrolopes.ankigen.data.model.OkResponse
import com.pedrolopes.ankigen.data.model.StatusUpdate
import com.pedrolopes.ankigen.data.model.TopicsResponse
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

/** Maps 1:1 onto the FastAPI routes in `api.py`. */
interface AnkiGenApi {

    @GET("api/health")
    suspend fun health(): HealthResponse

    @GET("api/cards")
    suspend fun listCards(
        @Query("topic") topic: String? = null,
        @Query("status") status: String? = null,
        @Query("card_type") cardType: String? = null,
    ): CardsResponse

    @GET("api/cards/{id}")
    suspend fun getCard(@Path("id") id: Int): Card

    @PUT("api/cards/{id}")
    suspend fun updateCard(@Path("id") id: Int, @Body body: CardUpdate): Card

    @DELETE("api/cards/{id}")
    suspend fun deleteCard(@Path("id") id: Int): OkResponse

    @PATCH("api/cards/{id}/status")
    suspend fun updateStatus(@Path("id") id: Int, @Body body: StatusUpdate): Card

    @PATCH("api/cards/batch-status")
    suspend fun batchStatus(@Body body: BatchStatusUpdate): BatchStatusResponse

    @POST("api/generate")
    suspend fun generate(@Body body: GenerateRequest): CardsResponse

    @GET("api/topics")
    suspend fun topics(): TopicsResponse

    @GET("api/counts")
    suspend fun counts(@Query("topic") topic: String? = null): CountsResponse

    @DELETE("api/clear")
    suspend fun clear(
        @Query("status") status: String,
        @Query("topic") topic: String? = null,
    ): ClearResponse
}
