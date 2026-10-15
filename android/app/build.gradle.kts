plugins {
    id("com.android.application")
}

val recordingsMaxGb = providers.gradleProperty("recordingsMaxGb")
    .orElse("5")
    .get()
    .toLongOrNull()
    ?: error("recordingsMaxGb precisa ser um inteiro maior que zero.")

if (recordingsMaxGb <= 0) {
    error("recordingsMaxGb precisa ser um inteiro maior que zero.")
}

android {
    namespace = "com.marcielbezerra.webcameras"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.marcielbezerra.webcameras"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        buildConfigField("long", "RECORDINGS_MAX_GB", "${recordingsMaxGb}L")
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.media3:media3-exoplayer:1.8.0")
    implementation("androidx.media3:media3-exoplayer-rtsp:1.8.0")
    implementation("androidx.media3:media3-ui:1.8.0")
}
