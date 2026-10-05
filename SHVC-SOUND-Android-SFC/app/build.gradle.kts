plugins { id("com.android.application") }
android {
    namespace = "com.shvc.sfclive"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.shvc.sfclive"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        ndk { abiFilters += "arm64-v8a" }
    }
}
