package br.com.torres.garcom

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator

/** Som e vibração dos avisos (chamado de mesa, pedido pronto). */
object Alertas {
    const val CANAL_ATIVO = "turno"
    const val CANAL_ALERTAS = "chamados"

    val VIBRAR_CHAMADO = longArrayOf(0, 400, 150, 400, 150, 400)
    val VIBRAR_PRONTO = longArrayOf(0, 250, 100, 250)

    fun criarCanais(ctx: Context) {
        if (Build.VERSION.SDK_INT < 26) return
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CANAL_ATIVO, "Turno ativo", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Aviso fixo enquanto o app está recebendo os chamados"
            setShowBadge(false)
        })
        nm.createNotificationChannel(NotificationChannel(CANAL_ALERTAS, "Chamados e pedidos prontos", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Mesa chamando o garçom, pedindo a conta ou pedido pronto para levar"
            enableVibration(true)
            vibrationPattern = VIBRAR_CHAMADO
            setSound(
                RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION),
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT).build(),
            )
        })
    }

    /** Usado com o app aberto (a página chama window.TorresApp.alertar). */
    fun tocar(ctx: Context, tipo: String) {
        vibrar(ctx, if (tipo == "garcom") VIBRAR_CHAMADO else VIBRAR_PRONTO)
        try {
            RingtoneManager.getRingtone(ctx, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION))?.play()
        } catch (e: Exception) {
            // sem som disponível: fica só a vibração
        }
    }

    @Suppress("DEPRECATION")
    private fun vibrar(ctx: Context, padrao: LongArray) {
        val v = ctx.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator ?: return
        if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createWaveform(padrao, -1)) else v.vibrate(padrao, -1)
    }
}
