plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "app.lecturenotes"
    compileSdk = 34

    defaultConfig {
        applicationId = "app.lecturenotes"
        minSdk = 26
        targetSdk = 34
        // GitHub Actions가 실행 번호로 버전을 올린다 (깔린 앱 위에 새 APK를 덮어 깔 수 있게)
        versionCode = (System.getenv("VERSION_CODE") ?: "1").toInt()
        versionName = "0.1.${System.getenv("VERSION_CODE") ?: "0"}"
    }

    signingConfigs {
        // 서명 키가 저장소 Secrets(ANDROID_KEYSTORE_BASE64 등)에 있으면 그 키로 서명한다 → 새 버전을 덮어 깔 수 있다.
        // 없으면 빌드 서버의 임시 디버그 키로 서명한다 → 새 버전은 지우고 다시 깔아야 한다 (자료는 서버에 있어 그대로).
        create("personal") {
            val keystore = System.getenv("ANDROID_KEYSTORE_PATH")
            if (keystore != null && file(keystore).exists()) {
                storeFile = file(keystore)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            val personal = signingConfigs.getByName("personal")
            signingConfig = if (personal.storeFile != null) personal else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.webkit:webkit:1.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // 폰 안 받아쓰기 엔진 (k2-fsa sherpa-onnx, Apache 2.0). 빌드 때 GitHub 릴리스에서 정해진 버전을 받아 libs/에 둔다
    implementation(files("libs/sherpa-onnx.aar"))
}
