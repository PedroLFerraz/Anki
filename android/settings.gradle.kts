pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        // AnkiDroid's public API is published through JitPack
        maven { url = uri("https://jitpack.io") }
    }
}

rootProject.name = "AnkiGen"
include(":app")
