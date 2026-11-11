package br.com.torres.garcom

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView

/**
 * Liga o app ao sistema da loja pelo IP do computador principal (digitado),
 * ou já pronto pelo link "Abrir no app" da página /app (QR code). Não há
 * busca automática: o IP digitado funciona em qualquer rede da loja.
 */
class ConectarActivity : Activity() {

    private lateinit var status: android.widget.TextView
    private lateinit var endereco: EditText
    private lateinit var conectar: android.widget.Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val c = this
        val coluna = LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(Telas.dp(c, 20), Telas.dp(c, 28), Telas.dp(c, 20), Telas.dp(c, 28))
        }
        coluna.addView(Telas.texto(c, "🛎️ Torres Garçom", 26f, negrito = true))
        coluna.addView(Telas.texto(c, "Ligue o app ao computador principal da loja. O celular precisa estar no Wi-Fi da loja.",
            16f, Telas.TEXTO_2))

        coluna.addView(Telas.texto(c, "IP do computador principal", 17f, negrito = true).also { Telas.espacamento(c, it, 24) })
        endereco = EditText(c).apply {
            hint = "Ex.: 192.168.0.10"
            setText(Preferencias.servidor(c)?.let { Rede.ipParaMostrar(it) } ?: "")
            setTextColor(Telas.TEXTO)
            setHintTextColor(Telas.TEXTO_2)
            textSize = 22f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            imeOptions = EditorInfo.IME_ACTION_GO
            setOnEditorActionListener { _, _, _ -> conectarDigitado(); true }
        }
        coluna.addView(endereco)
        conectar = Telas.botao(c, "Conectar", Telas.VERDE) { conectarDigitado() }
        Telas.espacamento(c, conectar)
        coluna.addView(conectar)
        status = Telas.texto(c, "", 15f, Telas.TEXTO_2)
        Telas.espacamento(c, status, 12)
        coluna.addView(status)

        coluna.addView(Telas.texto(c, "Onde vejo o IP? No computador principal: Administração → Configurações → Conexões, " +
            "ou no ícone laranja do Torres Comandas perto do relógio.", 15f, Telas.TEXTO_2).also {
            Telas.espacamento(c, it, 24)
        })

        setContentView(ScrollView(c).apply { setBackgroundColor(Telas.FUNDO); addView(coluna) })
        tratarLink(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        tratarLink(intent)
    }

    /** torrescomandas://conectar?servidor=http%3A%2F%2F192.168.0.10%3A8090 */
    private fun tratarLink(intent: Intent?) {
        val dados: Uri = intent?.data ?: return
        val url = Rede.normalizar(dados.getQueryParameter("servidor") ?: return) ?: return
        endereco.setText(Rede.ipParaMostrar(url))
        conectar(url)
    }

    private fun conectarDigitado() {
        val url = Rede.normalizar(endereco.text.toString())
        if (url == null) {
            status.text = "Digite o IP do computador principal (ex.: 192.168.0.10)."
            return
        }
        conectar(url)
    }

    private fun conectar(url: String) {
        val ip = Rede.ipParaMostrar(url)
        status.text = "Conectando a $ip..."
        conectar.isEnabled = false
        Thread {
            val s = Rede.identificar(url, 4000)
            // Não conectou: descobre se nada respondeu nesse IP ou se respondeu outro programa.
            val respondeu = s == null && Rede.portaAberta(url)
            runOnUiThread {
                conectar.isEnabled = true
                when {
                    s != null -> usar(s)
                    respondeu -> status.text = "O IP $ip respondeu, mas não é o Torres Comandas. Confira o IP no computador principal."
                    else -> status.text = "O computador principal não respondeu no IP $ip.\n\n" +
                        "• Confira o IP (Administração → Configurações → Conexões).\n" +
                        "• O celular precisa estar no Wi-Fi da loja (não nos dados móveis nem no Wi-Fi de visitantes).\n" +
                        "• O Torres Comandas precisa estar aberto no computador principal.\n" +
                        "• Teste no navegador do celular: http://$ip:${Rede.PORTA_PADRAO}/app — se também não abrir, " +
                        "é a rede ou o firewall/antivírus do computador principal bloqueando."
                }
            }
        }.start()
    }

    private fun usar(s: Sistema) {
        Preferencias.salvar(this, s)
        Preferencias.definirTurno(this, true)
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra("recarregar", true))
        finish()
    }
}
