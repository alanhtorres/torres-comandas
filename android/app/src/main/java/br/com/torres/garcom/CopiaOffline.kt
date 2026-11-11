package br.com.torres.garcom

import android.content.Context
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Cópia da tela do garçom guardada no celular (HTML + arquivos /static).
 * Longe do Wi-Fi, se o app precisar abrir a página de novo (o Android fechou
 * o app, o garçom tocou em "Recarregar"...), ela vem daqui: o garçom continua
 * anotando, e os pedidos ficam guardados na fila da página até o Wi-Fi voltar.
 */
object CopiaOffline {
    private const val PAGINA = "garcom.html"
    @Volatile private var ultimaAtualizacao = 0L

    private fun pasta(ctx: Context) = File(ctx.filesDir, "offline")

    fun temCopia(ctx: Context): Boolean = File(pasta(ctx), PAGINA).isFile

    /** Arquivo guardado para o caminho pedido pela página (ou null). */
    fun arquivo(ctx: Context, caminho: String): File? {
        val nome = when {
            caminho.trimEnd('/') == "/garcom" -> PAGINA
            caminho.startsWith("/static/") && !caminho.contains("..") -> caminho.removePrefix("/")
            else -> return null
        }
        return File(pasta(ctx), nome).takeIf { it.isFile }
    }

    fun tipo(caminho: String): String = when {
        caminho.endsWith(".css") -> "text/css"
        caminho.endsWith(".js") -> "application/javascript"
        caminho.endsWith(".png") -> "image/png"
        caminho.endsWith(".svg") -> "image/svg+xml"
        else -> "text/html"
    }

    /** Baixa de novo a página e os arquivos dela (com o login do garçom). */
    fun atualizar(ctx: Context, servidor: String, cookie: String?, agente: String) {
        val agora = System.currentTimeMillis()
        if (agora - ultimaAtualizacao < 60_000) return
        ultimaAtualizacao = agora
        Thread {
            try {
                val html = baixar("$servidor/garcom", cookie, agente) ?: return@Thread
                val texto = String(html, Charsets.UTF_8)
                // Só guarda a tela do garçom de verdade (não a de login).
                if (!texto.contains("abas-rodape")) return@Thread
                val destino = pasta(ctx).apply { mkdirs() }
                val arquivos = Regex("(?:src|href)=\"(/static/[^\"?#]+)").findAll(texto).map { it.groupValues[1] }.toSet()
                for (caminho in arquivos) {
                    if (caminho.contains("..")) continue
                    val dados = baixar(servidor + caminho, cookie, agente) ?: continue
                    gravar(File(destino, caminho.removePrefix("/")), dados)
                }
                gravar(File(destino, PAGINA), html)
            } catch (e: Exception) {
                // sem rede no meio do caminho: fica a cópia anterior
            }
        }.start()
    }

    private fun gravar(arquivo: File, dados: ByteArray) {
        arquivo.parentFile?.mkdirs()
        val temporario = File(arquivo.path + ".tmp")
        temporario.writeBytes(dados)
        temporario.renameTo(arquivo)
    }

    private fun baixar(url: String, cookie: String?, agente: String): ByteArray? {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 5000
        c.readTimeout = 8000
        c.instanceFollowRedirects = false
        c.useCaches = false
        c.setRequestProperty("User-Agent", agente)
        c.setRequestProperty("X-Automatico", "1")
        cookie?.let { c.setRequestProperty("Cookie", it) }
        return try {
            if (c.responseCode == 200) c.inputStream.use { it.readBytes() } else null
        } finally {
            c.disconnect()
        }
    }
}
