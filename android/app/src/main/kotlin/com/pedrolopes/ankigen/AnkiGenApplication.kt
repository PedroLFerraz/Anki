package com.pedrolopes.ankigen

import android.app.Application
import com.pedrolopes.ankigen.data.CardRepository
import com.pedrolopes.ankigen.data.anki.AnkiDroidExporter
import com.pedrolopes.ankigen.data.local.SettingsStore

/**
 * Manual service locator. A DI framework would be more ceremony than this
 * three-object graph justifies; swap in Hilt if the graph grows.
 */
class AnkiGenApplication : Application() {

    lateinit var settings: SettingsStore
        private set

    lateinit var repository: CardRepository
        private set

    lateinit var ankiDroid: AnkiDroidExporter
        private set

    override fun onCreate() {
        super.onCreate()
        settings = SettingsStore(this)
        repository = CardRepository(settings)
        ankiDroid = AnkiDroidExporter(this, settings)
    }
}
