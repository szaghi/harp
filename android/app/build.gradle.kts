plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

android {
    namespace = "org.szaghi.harp"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.szaghi.harp"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        ndk {
            // phones only; add "x86_64" to also run on the emulator
            abiFilters += listOf("arm64-v8a")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
}

chaquopy {
    defaultConfig {
        // 3.12 matches the system python3 of both Ubuntu 24.04 CI runners and
        // Stefano's WSL, so buildPython resolves without extra setup.
        version = "3.12"
        pip {
            // THE PHASE-1 SPIKE: whether astropy/pyerfa resolve from Chaquopy's
            // Android wheel repository is exactly what this build proves.
            install("numpy")
            install("astropy")
            install("astroplan")
            install("pyongc")
            install("pyyaml")
            install("tzdata")   // zoneinfo database (Android has no system tzdata for Python)
        }
    }
    sourceSets {
        getByName("main") {
            // Embed the repo's Python core directly: the app and the CLI share
            // src/harp as a single source of truth (the monorepo dividend).
            srcDir("../../src")
        }
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
}
