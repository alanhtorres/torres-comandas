package br.com.torres.garcom

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.LinearLayout

/**
 * Tela principal: a página do garçom do sistema, sempre aberta. Sair e voltar
 * (botão voltar, outro app, tela apagada) não perde nada: o app só vai para
 * segundo plano, e o pedido em anotação fica guardado no aparelho.
 */
class MainActivity : Activity() {

    companion object {
        /** O serviço só mostra notificação quando o app não está na frente. */
        @Volatile var visivel = false
    }

    private lateinit var web: WebView
    private lateinit var semConexao: LinearLayout
    private lateinit var textoSemConexao: android.widget.TextView
    private val principal = Handler(Looper.getMainLooper())
    private var avisouAtualizacao = false

    private val servidor get() = Preferencias.servidor(this)

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (servidor == null) {
            startActivity(Intent(this, ConectarActivity::class.java))
            finish()
            return
        }
        Alertas.criarCanais(this)

        // Permite inspecionar a página pelo cabo USB (só com a depuração USB do
        // Android ligada) — usado no teste automático do app.
        WebView.setWebContentsDebuggingEnabled(true)
        web = WebView(this).apply {
            setBackgroundColor(Telas.FUNDO)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            // o som dos alertas não depende de o garçom tocar na tela antes
            settings.mediaPlaybackRequiresUserGesture = false
            settings.userAgentString = settings.userAgentString + " TorresGarcomApp/" + versaoInstalada().second
            addJavascriptInterface(Ponte(), "TorresApp")
            webChromeClient = WebChromeClient() // mostra os confirm()/prompt() da página
            webViewClient = Navegador()
        }
        CookieManager.getInstance().setAcceptCookie(true)

        val raiz = FrameLayout(this)
        raiz.setBackgroundColor(Telas.FUNDO)
        raiz.addView(web, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        raiz.addView(montarSemConexao())
        setContentView(raiz)
        Telas.respeitarBarras(this, raiz)

        if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) carregar(intent.getStringExtra("aba"))
        pedirNotificacoes()
        AtendimentoService.iniciar(this)
        verificarAtualizacao()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        val aba = intent.getStringExtra("aba")
        when {
            intent.getBooleanExtra("recarregar", false) -> {
                AtendimentoService.parar(this)
                AtendimentoService.iniciar(this)
                carregar(aba)
            }
            // tocou numa notificação: vai direto para a aba (sem recarregar a página)
            aba != null -> web.evaluateJavascript(
                "history.replaceState(null, '', '#' + ${org.json.JSONObject.quote(aba)}); dispatchEvent(new HashChangeEvent('hashchange'))",
                null,
            )
        }
    }

    override fun onResume() {
        super.onResume()
        visivel = true
        if (::web.isInitialized) {
            web.onResume()
            // Com o app na frente, a própria tela mostra os avisos: limpa a barra.
            limparAvisos()
            AtendimentoService.iniciar(this)
        }
    }

    override fun onPause() {
        visivel = false
        if (::web.isInitialized) {
            guardarLogin()
            web.onPause()
        }
        super.onPause()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::web.isInitialized) web.saveState(outState)
    }

    @Deprecated("Mantido para Android antigo")
    override fun onBackPressed() {
        // Voltar nunca fecha o app: dentro da página volta a tela anterior; na
        // tela principal, só manda o app para segundo plano (como o botão Início).
        val naTelaPrincipal = Uri.parse(web.url ?: "").path?.trimEnd('/') == "/garcom"
        if (semConexao.visibility != View.VISIBLE && !naTelaPrincipal && web.canGoBack()) web.goBack() else moveTaskToBack(true)
    }

    private fun carregar(aba: String?) {
        val base = servidor ?: return
        esconderSemConexao()
        web.loadUrl("$base/garcom" + if (aba != null) "#$aba" else "")
    }

    private fun guardarLogin() {
        servidor?.let {
            Preferencias.salvarCookie(this, CookieManager.getInstance().getCookie(it))
            CookieManager.getInstance().flush()
        }
    }

    private fun limparAvisos() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 23) {
            nm.activeNotifications.filter { it.id != 1 }.forEach { nm.cancel(it.id) }
        }
    }

    // --- Sem conexão ----------------------------------------------------------

    private fun montarSemConexao(): LinearLayout {
        val c = this
        textoSemConexao = Telas.texto(c, "", 17f)
        semConexao = LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Telas.FUNDO)
            setPadding(Telas.dp(c, 24), Telas.dp(c, 24), Telas.dp(c, 24), Telas.dp(c, 24))
            visibility = View.GONE
            addView(Telas.texto(c, "📡 Sem conexão com o sistema", 22f, negrito = true))
            addView(textoSemConexao)
            addView(Telas.botao(c, "Tentar de novo", Telas.VERDE) { tentarDeNovo() }.also { Telas.espacamento(c, it, 16) })
            addView(Telas.botao(c, "Trocar o IP do computador principal", Telas.PAINEL) {
                startActivity(Intent(c, ConectarActivity::class.java))
            }.also { Telas.espacamento(c, it) })
        }
        return semConexao
    }

    private fun mostrarSemConexao() {
        textoSemConexao.text = "Confira se o celular está no Wi-Fi da loja e se o computador principal está ligado " +
            "com o Torres Comandas aberto.\nTentando de novo sozinho... (IP ${Rede.ipParaMostrar(servidor)})"
        semConexao.visibility = View.VISIBLE
        principal.removeCallbacksAndMessages(null)
        principal.postDelayed({ tentarDeNovo() }, 5000)
    }

    private fun esconderSemConexao() {
        principal.removeCallbacksAndMessages(null)
        semConexao.visibility = View.GONE
    }

    /** Testa o IP salvo de novo (o app não procura sozinho: o IP do principal é fixo). */
    private fun tentarDeNovo() {
        val atual = servidor ?: return
        principal.removeCallbacksAndMessages(null)
        Thread {
            val s = Rede.identificar(atual)
            runOnUiThread {
                if (isFinishing) return@runOnUiThread
                if (s != null) {
                    carregar(null)
                } else {
                    mostrarSemConexao()
                }
            }
        }.start()
    }

    /**
     * Contingência: sem Wi-Fi, a tela do garçom vem da cópia guardada no
     * celular e as chamadas ao sistema respondem "sem conexão" na hora (a
     * página guarda os pedidos na fila dela). Volta sozinho quando o sistema
     * responder de novo.
     */
    @Volatile private var semRede = false

    private fun entrarSemRede() {
        semRede = true
        esconderSemConexao()
        web.loadUrl("$servidor/garcom")
        Thread {
            while (semRede && !isFinishing) {
                Thread.sleep(5000)
                val atual = servidor ?: break
                if (Rede.identificar(atual) != null) semRede = false
            }
        }.start()
    }

    private val PAGINAS_DO_APP = listOf("/garcom", "/login", "/sair", "/primeiro-acesso", "/app")

    private inner class Navegador : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val destino = request.url
            val base = Uri.parse(servidor ?: return false)
            if (destino.host == base.host && destino.port == base.port) {
                // Dentro do app só existe a tela do garçom (e o login): o
                // "Início", as abas e o painel não abrem aqui.
                val caminho = destino.path ?: ""
                val permitido = PAGINAS_DO_APP.any { caminho == it || caminho.startsWith("$it/") }
                if (permitido) return false
                view.loadUrl("${servidor}/garcom")
                return true
            }
            // Links de fora do sistema (WhatsApp, sites): abre no app certo.
            try {
                startActivity(Intent(Intent.ACTION_VIEW, destino))
            } catch (e: Exception) {
                // nenhum app abre esse link
            }
            return true
        }

        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
            if (!semRede) return null
            val base = Uri.parse(servidor ?: return null)
            val destino = request.url
            if (destino.host != base.host || destino.port != base.port) return null
            val caminho = destino.path ?: ""
            if (caminho.startsWith("/api/")) {
                return WebResourceResponse("application/json", "utf-8", 503, "Sem conexao",
                    mapOf("Cache-Control" to "no-store"),
                    "{\"ok\":false,\"erro\":\"Sem conexão com o sistema\"}".toByteArray().inputStream())
            }
            val arquivo = CopiaOffline.arquivo(this@MainActivity, caminho) ?: return null
            return WebResourceResponse(CopiaOffline.tipo(caminho), "utf-8", arquivo.inputStream())
        }

        override fun onPageFinished(view: WebView, url: String) {
            guardarLogin()
            // Com conexão, guarda a cópia da tela para usar longe do Wi-Fi.
            val atual = servidor
            if (!semRede && atual != null && Uri.parse(url).path?.trimEnd('/') == "/garcom") {
                CopiaOffline.atualizar(this@MainActivity, atual, CookieManager.getInstance().getCookie(atual),
                    view.settings.userAgentString)
            }
            // Na tela do garçom, esquece o caminho até ela (ex.: o login):
            // o botão voltar não deve levar de volta para a tela de entrar.
            if (Uri.parse(url).path?.trimEnd('/') == "/garcom") view.clearHistory()
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (!request.isForMainFrame) return
            // Sem Wi-Fi: abre a cópia guardada da tela do garçom (contingência).
            if (!semRede && CopiaOffline.temCopia(this@MainActivity)) entrarSemRede() else mostrarSemConexao()
        }
    }

    // --- Ponte com a página (window.TorresApp) -------------------------------

    private inner class Ponte {
        @JavascriptInterface
        fun alertar(tipo: String) = Alertas.tocar(this@MainActivity, tipo)

        @JavascriptInterface
        fun configuracoes() = runOnUiThread { mostrarConfiguracoes() }

        @JavascriptInterface
        fun versao(): String = versaoInstalada().second
    }

    private fun mostrarConfiguracoes() {
        val turno = Preferencias.turnoAtivo(this)
        val opcoes = mutableListOf<Pair<String, () -> Unit>>()
        opcoes += (if (turno) "⏹ Encerrar turno (parar os avisos)" else "▶ Começar turno (receber os avisos)") to {
            Preferencias.definirTurno(this, !turno)
            if (turno) AtendimentoService.parar(this) else AtendimentoService.iniciar(this)
        }
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        if (Build.VERSION.SDK_INT >= 23 && !pm.isIgnoringBatteryOptimizations(packageName)) {
            opcoes += "🔋 Não deixar o Android pausar os avisos" to { pedirSemEconomiaBateria() }
        }
        opcoes += "🔄 Recarregar a página" to { carregar(null) }
        opcoes += "🔗 Trocar o IP do computador principal" to { startActivity(Intent(this, ConectarActivity::class.java)) }
        AlertDialog.Builder(this)
            .setTitle("Torres Garçom ${versaoInstalada().second}")
            .setMessage("Ligado a: ${Preferencias.loja(this)} (${servidor?.removePrefix("http://")})\n" +
                "Avisos em segundo plano: ${if (turno) "ligados" else "desligados"}")
            .setItems(opcoes.map { it.first }.toTypedArray()) { _, i -> opcoes[i].second() }
            .setNegativeButton("Fechar", null)
            .show()
    }

    @SuppressLint("BatteryLife")
    private fun pedirSemEconomiaBateria() {
        if (Build.VERSION.SDK_INT < 23) return
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        } catch (e: Exception) {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun pedirNotificacoes() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        // com a permissão dada agora, o aviso fixo do turno aparece
        AtendimentoService.parar(this)
        AtendimentoService.iniciar(this)
    }

    // --- Versão nova do app -----------------------------------------------------

    @Suppress("DEPRECATION")
    private fun versaoInstalada(): Pair<Long, String> {
        val info = packageManager.getPackageInfo(packageName, 0)
        val codigo = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()
        return Pair(codigo, info.versionName ?: "")
    }

    /** O sistema do PC traz a versão mais nova do app: avisa para atualizar. */
    private fun verificarAtualizacao() {
        val base = servidor ?: return
        Thread {
            val s = Rede.identificar(base) ?: return@Thread
            if (s.appVersaoCodigo <= versaoInstalada().first) return@Thread
            runOnUiThread {
                if (avisouAtualizacao || isFinishing) return@runOnUiThread
                avisouAtualizacao = true
                AlertDialog.Builder(this)
                    .setTitle("Nova versão do app")
                    .setMessage("O sistema da loja foi atualizado e tem uma versão nova do app do garçom. Baixar e instalar agora?")
                    .setPositiveButton("Atualizar") { _, _ ->
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$base/app")))
                    }
                    .setNegativeButton("Depois", null)
                    .show()
            }
        }.start()
    }
}
