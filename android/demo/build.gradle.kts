plugins { id("com.android.application") }

android {
    namespace = "com.novaperf.demo"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.novaperf.demo"
        minSdk = 23
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    lint { abortOnError = false; checkReleaseBuilds = false }
}

dependencies {
    implementation(project(":novaperf-sdk"))
}
