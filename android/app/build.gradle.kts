// App Android do garçom: abre a tela /garcom do Torres Comandas e avisa os
// chamados em segundo plano. Gerado pelo GitHub Actions (ver
// .github/workflows/instalador.yml) e embutido no instalador do Windows.
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Mesma versão do sistema (src/comandas/__init__.py): 2.6.0 -> versionCode 20600.
val versaoSistema: String = Regex("__version__ = \"([0-9]+\\.[0-9]+\\.[0-9]+)\"")
    .find(rootDir.resolve("../src/comandas/__init__.py").readText())!!.groupValues[1]
val partesVersao = versaoSistema.split(".").map { it.toInt() }

// Chave de assinatura: precisa ser SEMPRE a mesma, senão o Android não deixa
// atualizar o app por cima. Vem dos segredos do GitHub (ANDROID_KEYSTORE_*).
val chave: String? = System.getenv("ANDROID_KEYSTORE")

android {
    namespace = "br.com.torres.garcom"
    compileSdk = 35

    defaultConfig {
        applicationId = "br.com.torres.garcom"
        minSdk = 24
        targetSdk = 35
        versionName = versaoSistema
        versionCode = partesVersao[0] * 10000 + partesVersao[1] * 100 + partesVersao[2]
    }

    signingConfigs {
        create("loja") {
            if (chave != null) {
                storeFile = file(chave)
                storePassword = System.getenv("ANDROID_KEYSTORE_SENHA")
                keyAlias = "torres"
                keyPassword = System.getenv("ANDROID_KEYSTORE_SENHA")
                storeType = "pkcs12"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (chave != null) "loja" else "debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    lint {
        checkReleaseBuilds = false
    }
}
