plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.shvc.soundplayer"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.shvc.soundplayer"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.core.ktx)
    implementation(libs.material)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    implementation("com.github.mik3y:usb-serial-for-android:3.7.0")  // ← この行を追加
    implementation("androidx.documentfile:documentfile:1.0.1")  // SPCフォルダ選択(SAF)用
}