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
        versionCode = 8
        versionName = "0.3.0"
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
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    // Camera: the horizon reticle (phase 2b) and the Shoot tab.
    //
    // The 1.5 line is required by Shoot, not optional: DNG/RAW still capture
    // (ImageCapture.OUTPUT_FORMAT_RAW, getImageCaptureCapabilities) does not
    // exist in 1.4.x at all. Manual sensor control (exposure/ISO/focus) has no
    // first-class CameraX API and rides on Camera2Interop from camera-camera2,
    // which must stay at the same version as camera-core.
    //
    // PINNED TO 1.5.x DELIBERATELY: 1.6.x raises its floor to compileSdk 36 and
    // AGP 8.9.1, which this project (compileSdk 35, AGP 8.7.3) does not meet --
    // :app:checkDebugAarMetadata fails outright. 1.5.3 targets compileSdk 35
    // and carries the same RAW API, so it buys nothing to chase 1.6 until the
    // whole toolchain moves.
    implementation("androidx.camera:camera-core:1.5.3")
    implementation("androidx.camera:camera-camera2:1.5.3")
    implementation("androidx.camera:camera-lifecycle:1.5.3")
    implementation("androidx.camera:camera-view:1.5.3")
    // ListenableFuture.await(): CameraX's provider and Camera2CameraControl are
    // future-based, and the Shoot tab drives them from coroutines.
    implementation("androidx.concurrent:concurrent-futures-ktx:1.2.0")
}
