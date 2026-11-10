plugins { id("com.android.library") }

android {
    namespace = "com.novaperf.sdk"
    compileSdk = 36

    defaultConfig {
        minSdk = 23
        consumerProguardFiles("consumer-rules.pro")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    lint { abortOnError = false; checkReleaseBuilds = false }
}

dependencies {
    // 零第三方依赖，零 native，零 root
}
