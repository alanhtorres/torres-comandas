package br.com.torres.garcom

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import org.json.JSONObject

/**
 * Fica rodando durante o turno (com um aviso fixo na barra de notificações) e
 * consulta o sistema a cada poucos segundos: quando uma mesa chama pelo QR
 * code ou um pedido fica pronto, mostra uma notificação com som e vibração —
 * mesmo com o celular no bolso, a tela apagada ou outro app aberto.
 */
class AtendimentoService : Service() {

    companion object {
        private const val ID_FIXA = 1
        private const val BASE_CHAMADO = 10_000
        private const val BASE_PRONTO = 1_000_000
        const val ACAO_PARAR = "br.com.torres.garcom.PARAR"

        fun iniciar(ctx: Context) {
            if (!Preferencias.turnoAtivo(ctx) || Preferencias.servidor(ctx) == null) return
            val i = Intent(ctx, AtendimentoService::class.java)
            try {
                if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i) else ctx.startService(i)
            } catch (e: Exception) {
                // Android não deixou iniciar agora (app em segundo plano): tenta ao abrir o app
            }
        }

        fun parar(ctx: Context) {
            ctx.stopService(Intent(ctx, AtendimentoService::class.java))
        }

        fun idNotificacaoChamado(id: Int) = BASE_CHAMADO + id
    }

    @Volatile private var rodando = false
    private var linha: Thread? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var textoFixo = ""

    private val nm by lazy { getSystemService(NOTIFICATION_SERVICE) as NotificationManager }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Alertas.criarCanais(this)
        startForeground(ID_FIXA, notificacaoFixa("Conectando ao sistema..."))
        // Mantém o Wi-Fi e a consulta funcionando com a tela apagada.
        wakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "TorresGarcom:turno").apply { setReferenceCounted(false); acquire() }
        @Suppress("DEPRECATION")
        wifiLock = (applicationContext.getSystemService(WIFI_SERVICE) as WifiManager)
            .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "TorresGarcom:turno").apply { setReferenceCounted(false); acquire() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACAO_PARAR) {
            Preferencias.definirTurno(this, false)
            stopSelf()
            return START_NOT_STICKY
        }
        // Reafirma o aviso fixo a cada pedido de início (o Android exige
        // startForeground depois de cada startForegroundService).
        startForeground(ID_FIXA, notificacaoFixa(textoFixo.ifEmpty { "Conectando ao sistema..." }))
        if (!rodando) {
            rodando = true
            linha = Thread({ laco() }, "turno").apply { start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        rodando = false
        linha?.interrupt()
        wakeLock?.release()
        wifiLock?.release()
        super.onDestroy()
    }

    private fun laco() {
        var versao = 0
        var falhas = 0
        var chamadosVistos: Map<Int, String>? = null
        var prontosVistos: Map<Int, String>? = null
        while (rodando) {
            var espera = 3000L
            try {
                val (codigo, corpo) = Rede.requisitar(this, "GET", "/api/estado" + if (versao > 0) "?v=$versao" else "")
                when (codigo) {
                    200 -> {
                        falhas = 0
                        val j = JSONObject(corpo)
                        if (j.optBoolean("mudou", true)) {
                            versao = j.optInt("versao")
                            val chamados = chamados(j)
                            val prontos = prontos(j)
                            avisarNovos(chamadosVistos, chamados, BASE_CHAMADO, true)
                            avisarNovos(prontosVistos, prontos, BASE_PRONTO, false)
                            chamadosVistos = chamados
                            prontosVistos = prontos
                        }
                        atualizarFixa("Recebendo os chamados — ${Preferencias.loja(this)}")
                    }
                    401, 403 -> {
                        versao = 0
                        chamadosVistos = null
                        prontosVistos = null
                        atualizarFixa("Abra o app e entre com o seu usuário para receber os chamados")
                        espera = 10_000
                    }
                    else -> throw IllegalStateException("HTTP $codigo")
                }
            } catch (e: InterruptedException) {
                return
            } catch (e: Exception) {
                falhas++
                if (falhas >= 3) atualizarFixa("Sem conexão com o sistema da loja — tentando de novo...")
                espera = if (falhas >= 3) 6000 else 3000
            }
            try {
                Thread.sleep(espera)
            } catch (e: InterruptedException) {
                return
            }
        }
    }

    /** id do chamado -> texto ("Mesa 5 está chamando"). */
    private fun chamados(j: JSONObject): Map<Int, String> {
        val r = linkedMapOf<Int, String>()
        val lista = j.optJSONArray("chamados_garcom") ?: return r
        for (i in 0 until lista.length()) {
            val c = lista.getJSONObject(i)
            val mesa = c.optString("mesa")
            r[c.getInt("id")] = if (c.optString("tipo") == "conta") "🧾 Mesa $mesa pediu a conta" else "🙋 Mesa $mesa está chamando"
        }
        return r
    }

    /** Pedidos de mesa/comanda prontos para levar (mesma regra da aba "Entregar"). */
    private fun prontos(j: JSONObject): Map<Int, String> {
        val r = linkedMapOf<Int, String>()
        val lista = j.optJSONArray("pedidos") ?: return r
        for (i in 0 until lista.length()) {
            val p = lista.getJSONObject(i)
            val status = p.optString("status")
            if (status != "pronto" && status != "chamado") continue
            val mesa = if (p.isNull("mesa")) "" else p.optString("mesa")
            val comanda = if (p.isNull("comanda_numero")) "" else p.optString("comanda_numero")
            if (mesa.isEmpty() && comanda.isEmpty()) continue
            val onde = if (mesa.isNotEmpty()) "Mesa $mesa" else "Comanda $comanda"
            r[p.getInt("id")] = "🍽️ Pedido ${p.optString("codigo")} pronto — $onde"
        }
        return r
    }

    private fun avisarNovos(antes: Map<Int, String>?, agora: Map<Int, String>, base: Int, chamado: Boolean) {
        // Some da barra o que já foi resolvido (atendido/entregue em outro aparelho).
        antes?.keys?.filter { it !in agora }?.forEach { nm.cancel(base + it) }
        if (antes == null) return // primeira leitura: não avisa o que já estava lá
        for ((id, texto) in agora) {
            if (id in antes) continue
            // Com o app aberto na frente, a própria tela toca e vibra.
            if (MainActivity.visivel) continue
            nm.notify(base + id, notificacaoAlerta(id, texto, chamado))
        }
    }

    private fun abrirApp(aba: String, codigo: Int): PendingIntent {
        val i = Intent(this, MainActivity::class.java)
            .putExtra("aba", aba)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        return PendingIntent.getActivity(this, codigo, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    @Suppress("DEPRECATION")
    private fun construtor(canal: String): Notification.Builder =
        if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, canal) else Notification.Builder(this)

    @Suppress("DEPRECATION")
    private fun notificacaoAlerta(id: Int, texto: String, chamado: Boolean): Notification {
        val b = construtor(Alertas.CANAL_ALERTAS)
            .setSmallIcon(R.drawable.ic_notificacao)
            .setContentTitle(texto)
            .setContentText(if (chamado) "Toque para abrir o app" else "Toque para ver o que levar")
            .setContentIntent(abrirApp(if (chamado) "novo" else "entregar", (if (chamado) BASE_CHAMADO else BASE_PRONTO) + id))
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
            .setWhen(System.currentTimeMillis())
            .setShowWhen(true)
        if (Build.VERSION.SDK_INT < 26) {
            b.setPriority(Notification.PRIORITY_HIGH)
            b.setDefaults(Notification.DEFAULT_SOUND)
            b.setVibrate(if (chamado) Alertas.VIBRAR_CHAMADO else Alertas.VIBRAR_PRONTO)
        }
        if (chamado) {
            val atendi = Intent(this, AcaoReceiver::class.java).setAction(AcaoReceiver.ACAO_ATENDI).putExtra("id", id)
            val pi = PendingIntent.getBroadcast(this, id, atendi, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            b.addAction(Notification.Action.Builder(null, "✓ Atendi", pi).build())
        }
        return b.build()
    }

    private fun notificacaoFixa(texto: String): Notification {
        val parar = PendingIntent.getService(
            this, 1, Intent(this, AtendimentoService::class.java).setAction(ACAO_PARAR),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return construtor(Alertas.CANAL_ATIVO)
            .setSmallIcon(R.drawable.ic_notificacao)
            .setContentTitle("Torres Garçom — turno ativo")
            .setContentText(texto)
            .setOngoing(true)
            .setContentIntent(abrirApp("novo", 2))
            .addAction(Notification.Action.Builder(null, "Encerrar turno", parar).build())
            .build()
    }

    private fun atualizarFixa(texto: String) {
        if (texto == textoFixo) return
        textoFixo = texto
        nm.notify(ID_FIXA, notificacaoFixa(texto))
    }
}
