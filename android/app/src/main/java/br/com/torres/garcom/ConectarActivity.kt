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
 * Liga o app ao sistema da loja: procurando o PC na rede, pelo endereço
 * digitado, ou já pronto pelo link "Abrir no app" da página /app (QR code).
 */
class ConectarActivity : Activity() {

    private lateinit var status: android.widget.TextView
    private lateinit var achados: LinearLayout
    private lateinit var endereco: EditText
    @Volatile private var procurando = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val c = this
        val coluna = LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(Telas.dp(c, 20), Telas.dp(c, 28), Telas.dp(c, 20), Telas.dp(c, 28))
        }
        coluna.addView(Telas.texto(c, "🛎️ Torres Garçom", 26f, negrito = true))
        coluna.addView(Telas.texto(c, "Ligue o app ao sistema da loja. O celular precisa estar no Wi-Fi da loja.", 16f, Telas.TEXTO_2))

        val procurar = Telas.botao(c, "🔍 Procurar o sistema na rede", Telas.VERDE) { procurar() }
        Telas.espacamento(c, procurar, 18)
        coluna.addView(procurar)
        status = Telas.texto(c, "", 15f, Telas.TEXTO_2)
        coluna.addView(status)
        achados = LinearLayout(c).apply { orientation = LinearLayout.VERTICAL }
        coluna.addView(achados)

        coluna.addView(Telas.texto(c, "Ou digite o endereço que aparece no PC (ex.: 192.168.0.10:8090):", 15f, Telas.TEXTO_2).also {
            Telas.espacamento(c, it, 24)
        })
        endereco = EditText(c).apply {
            hint = "192.168.0.10:8090"
            setText(Preferencias.servidor(c)?.removePrefix("http://") ?: "")
            setTextColor(Telas.TEXTO)
            setHintTextColor(Telas.TEXTO_2)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            imeOptions = EditorInfo.IME_ACTION_GO
            setOnEditorActionListener { _, _, _ -> conectarDigitado(); true }
        }
        coluna.addView(endereco)
        val conectar = Telas.botao(c, "Conectar") { conectarDigitado() }
        Telas.espacamento(c, conectar)
        coluna.addView(conectar)

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
        endereco.setText(url.removePrefix("http://"))
        conectar(url)
    }

    private fun conectarDigitado() {
        val url = Rede.normalizar(endereco.text.toString())
        if (url == null) {
            status.text = "Digite o endereço do PC, como aparece na tela inicial do sistema."
            return
        }
        conectar(url)
    }

    private fun conectar(url: String) {
        status.text = "Conectando a $url..."
        Thread {
            val s = Rede.identificar(url)
            runOnUiThread {
                if (s == null) {
                    status.text = "Não encontrei o sistema em $url. Confira se o celular está no Wi-Fi da loja e se o programa está aberto no PC."
                } else {
                    usar(s)
                }
            }
        }.start()
    }

    private fun procurar() {
        if (procurando) return
        procurando = true
        achados.removeAllViews()
        status.text = "Procurando na rede da loja... (leva alguns segundos)"
        val portas = linkedSetOf(Rede.PORTA_PADRAO, Rede.portaDe(Preferencias.servidor(this)))
        Thread {
            val lista = Rede.procurar(portas) { s -> runOnUiThread { mostrarAchado(s) } }
            runOnUiThread {
                procurando = false
                status.text = when (lista.size) {
                    0 -> "Nenhum sistema encontrado. O celular está no Wi-Fi da loja? O programa está aberto no PC? " +
                        "Se a porta for outra, digite o endereço abaixo."
                    1 -> "Sistema encontrado:"
                    else -> "Encontrei ${lista.size} sistemas. Toque no da sua loja:"
                }
                // Achou um só: conecta direto.
                if (lista.size == 1) usar(lista[0])
            }
        }.start()
    }

    private fun mostrarAchado(s: Sistema) {
        val b = Telas.botao(this, "${s.loja}\n${s.url.removePrefix("http://")}", Telas.PAINEL) { usar(s) }
        Telas.espacamento(this, b, 8)
        achados.addView(b)
    }

    private fun usar(s: Sistema) {
        Preferencias.salvar(this, s)
        Preferencias.definirTurno(this, true)
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra("recarregar", true))
        finish()
    }
}
