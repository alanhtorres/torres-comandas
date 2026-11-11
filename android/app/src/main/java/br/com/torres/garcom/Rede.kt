package br.com.torres.garcom

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URL

/** Um Torres Comandas encontrado na rede. */
data class Sistema(val url: String, val id: String, val loja: String, val appVersaoCodigo: Int)

/** O que o app guarda no aparelho: a qual sistema está ligado e o login (cookie). */
object Preferencias {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("torres", Context.MODE_PRIVATE)

    fun servidor(ctx: Context): String? = prefs(ctx).getString("servidor", null)
    fun idSistema(ctx: Context): String? = prefs(ctx).getString("id", null)
    fun loja(ctx: Context): String = prefs(ctx).getString("loja", null) ?: "Torres Comandas"

    fun salvar(ctx: Context, s: Sistema) {
        prefs(ctx).edit().putString("servidor", s.url).putString("id", s.id).putString("loja", s.loja).apply()
    }

    // Cópia do cookie de login do WebView, para o serviço de alertas usar
    // (o serviço roda sem a tela aberta).
    fun cookie(ctx: Context): String? = prefs(ctx).getString("cookie", null)
    fun salvarCookie(ctx: Context, cookie: String?) {
        prefs(ctx).edit().putString("cookie", cookie).apply()
    }

    /** "Turno": enquanto ativo, o serviço fica recebendo os chamados. */
    fun turnoAtivo(ctx: Context): Boolean = prefs(ctx).getBoolean("turno", true)
    fun definirTurno(ctx: Context, ativo: Boolean) {
        prefs(ctx).edit().putBoolean("turno", ativo).apply()
    }
}

object Rede {
    const val PORTA_PADRAO = 8090

    /** Aceita "192.168.0.10", "192.168.0.10:8090" ou "http://192.168.0.10:8090/garcom". */
    fun normalizar(texto: String): String? {
        var t = texto.trim()
        if (t.isEmpty()) return null
        if (!t.startsWith("http://") && !t.startsWith("https://")) t = "http://$t"
        return try {
            val u = URL(t)
            if (u.host.isNullOrEmpty()) return null
            val porta = if (u.port > 0) u.port else PORTA_PADRAO
            "${u.protocol}://${u.host}:$porta"
        } catch (e: Exception) {
            null
        }
    }

    /** Pergunta ao endereço se ele é um Torres Comandas (rota pública /api/identificar). */
    fun identificar(url: String, timeoutMs: Int = 2500): Sistema? {
        return try {
            val c = URL("$url/api/identificar").openConnection() as HttpURLConnection
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            c.useCaches = false
            try {
                if (c.responseCode != 200) return null
                val j = JSONObject(c.inputStream.bufferedReader().readText())
                if (j.optString("sistema") != "torres-comandas") return null
                val app = j.optJSONObject("app")
                Sistema(url, j.optString("id"), j.optString("loja", "Torres Comandas"), app?.optInt("versao_codigo") ?: 0)
            } finally {
                c.disconnect()
            }
        } catch (e: Exception) {
            null
        }
    }

    /** "http://192.168.0.10:8090" -> "192.168.0.10" (a porta só aparece se não for a padrão). */
    fun ipParaMostrar(url: String?): String {
        val t = (url ?: "").removePrefix("http://").removePrefix("https://")
        return t.removeSuffix(":$PORTA_PADRAO")
    }

    /** Algum programa atende nesse IP e porta? (Para explicar por que não conectou.) */
    fun portaAberta(url: String, timeoutMs: Int = 2500): Boolean = try {
        val u = URL(url)
        Socket().use { it.connect(InetSocketAddress(u.host, if (u.port > 0) u.port else PORTA_PADRAO), timeoutMs) }
        true
    } catch (e: Exception) {
        false
    }

    /** Requisição simples com o login do garçom (usada pelo serviço e pelas notificações). */
    fun requisitar(ctx: Context, metodo: String, caminho: String, timeoutMs: Int = 6000): Pair<Int, String> {
        val servidor = Preferencias.servidor(ctx) ?: return Pair(0, "")
        val c = URL(servidor + caminho).openConnection() as HttpURLConnection
        c.requestMethod = metodo
        c.connectTimeout = timeoutMs
        c.readTimeout = timeoutMs
        c.useCaches = false
        // Atualização automática: não conta como uso do sistema.
        c.setRequestProperty("X-Automatico", "1")
        Preferencias.cookie(ctx)?.let { c.setRequestProperty("Cookie", it) }
        if (metodo == "POST") {
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write("{}".toByteArray()) }
        }
        try {
            val codigo = c.responseCode
            val corpo = (if (codigo < 400) c.inputStream else c.errorStream)?.bufferedReader()?.readText() ?: ""
            return Pair(codigo, corpo)
        } finally {
            c.disconnect()
        }
    }
}
