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
        versionCode = 7
        versionName = "0.2.0"
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
        // astropy's unit parser (PLY) generates generic_parsetab.py inside its
        // own package dir at first use; Chaquopy's default read-only asset
        // loading makes that fail ("'m / (s)' did not parse as unit ... No
        // such file"). Extracting astropy to a real writable directory lets
        // PLY generate its tables on first import.
        extractPackages("astropy")
        pip {
            // THE PHASE-1 SPIKE: whether astropy/pyerfa resolve from Chaquopy's
            // Android wheel repository is exactly what this build proves.
            install("numpy")
            install("astropy")
            // LOCAL WHEEL REQUIRED: Chaquopy's index shadows PyPI for names it
            // carries, and its astroplan is a stale <=0.7 that imports the
            // private _get_download_cache_locs removed in astropy 5. PyPI has
            // no astroplan wheel (sdist only), so we commit the pure-Python
            // wheel (built with `pip wheel astroplan==0.10.1 --no-deps`) and
            // install it by path — deterministic, no index games.
            install("wheels/astroplan-0.10.1-py3-none-any.whl")
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
    // camera reticle (phase 2b)
    implementation("androidx.camera:camera-core:1.4.1")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")
}
