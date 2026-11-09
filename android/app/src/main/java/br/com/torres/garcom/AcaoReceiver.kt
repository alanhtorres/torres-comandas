package br.com.torres.garcom

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.widget.Toast
import android.os.Handler
import android.os.Looper

/** Botão "✓ Atendi" da notificação: marca o chamado sem precisar abrir o app. */
class AcaoReceiver : BroadcastReceiver() {
    companion object {
        const val ACAO_ATENDI = "br.com.torres.garcom.ATENDI"
    }

    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action != ACAO_ATENDI) return
        val id = intent.getIntExtra("id", 0)
        if (id <= 0) return
        val pendente = goAsync()
        val app = ctx.applicationContext
        Thread {
            val ok = try {
                Rede.requisitar(app, "POST", "/api/garcom/$id/atender").first == 200
            } catch (e: Exception) {
                false
            }
            if (ok) {
                (app.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                    .cancel(AtendimentoService.idNotificacaoChamado(id))
            }
            Handler(Looper.getMainLooper()).post {
                Toast.makeText(app, if (ok) "Chamado marcado como atendido" else "Não foi possível marcar: abra o app", Toast.LENGTH_SHORT).show()
                pendente.finish()
            }
        }.start()
    }
}
