package br.com.torres.garcom

import android.app.Activity
import android.content.Context
import android.os.Build
import android.view.View
import android.view.WindowInsets
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.widget.Button
import android.widget.TextView

/** Pedaços de tela montados em código (sem XML), nas cores do sistema. */
object Telas {
    const val FUNDO = 0xFF0F172A.toInt()
    const val PAINEL = 0xFF1E293B.toInt()
    const val TEXTO = 0xFFE2E8F0.toInt()
    const val TEXTO_2 = 0xFF94A3B8.toInt()
    const val DESTAQUE = 0xFF38BDF8.toInt()
    const val VERDE = 0xFF22C55E.toInt()

    /**
     * Mantém a tela do app entre a barra de cima (relógio, bateria) e a de
     * baixo (voltar, início) e acima do teclado. No Android 15 o app ocupa a
     * tela toda, por baixo das barras, e os botões da página ficavam tapados.
     * Do Android 11 em diante o app sempre cuida disso (igual em todos); nos
     * mais antigos o próprio Android já deixa o espaço das barras.
     */
    fun respeitarBarras(activity: Activity, raiz: View) {
        if (Build.VERSION.SDK_INT < 30) return
        activity.window.setDecorFitsSystemWindows(false)
        raiz.setOnApplyWindowInsetsListener { v, insets ->
            val b = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or WindowInsets.Type.ime())
            v.setPadding(b.left, b.top, b.right, b.bottom)
            WindowInsets.CONSUMED
        }
        raiz.requestApplyInsets()
    }

    fun dp(ctx: Context, v: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), ctx.resources.displayMetrics).toInt()

    fun texto(ctx: Context, conteudo: String, tamanhoSp: Float = 16f, cor: Int = TEXTO, negrito: Boolean = false) =
        TextView(ctx).apply {
            text = conteudo
            setTextColor(cor)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, tamanhoSp)
            if (negrito) setTypeface(typeface, Typeface.BOLD)
            setPadding(0, dp(ctx, 6), 0, dp(ctx, 6))
        }

    fun botao(ctx: Context, rotulo: String, cor: Int = DESTAQUE, aoTocar: () -> Unit) =
        Button(ctx).apply {
            text = rotulo
            isAllCaps = false
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(if (cor == PAINEL) TEXTO else FUNDO)
            gravity = Gravity.CENTER
            background = GradientDrawable().apply {
                cornerRadius = dp(ctx, 12).toFloat()
                setColor(cor)
            }
            setPadding(dp(ctx, 16), dp(ctx, 14), dp(ctx, 16), dp(ctx, 14))
            setOnClickListener { aoTocar() }
        }

    fun espacamento(ctx: Context, v: android.view.View, topo: Int = 10) {
        val lp = android.widget.LinearLayout.LayoutParams(
            android.widget.LinearLayout.LayoutParams.MATCH_PARENT,
            android.widget.LinearLayout.LayoutParams.WRAP_CONTENT,
        )
        lp.topMargin = dp(ctx, topo)
        v.layoutParams = lp
    }
}
