"""Servidor web: telas (caixa, cozinha, painel, cliente via QR code,
administração) e a API que todas elas usam. Cada página e cada ação confere
se o usuário logado tem a permissão correspondente."""
import io
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

import segno
from flask import (
    Flask, Response, abort, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError

from . import impressora
from .banco import FORMAS_PAGAMENTO, MODELOS, PERMISSOES, PERMISSOES_ADMIN, Banco, ErroNegocio

EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
# Formatos que qualquer navegador de TV/celular toca sem conversão.
EXT_VIDEO = {".mp4", ".webm", ".m4v"}

log = logging.getLogger("comandas.servidor")


def _salvar_foto(arquivo_enviado, destino: Path, lado_maximo: int) -> None:
    try:
        img = Image.open(arquivo_enviado.stream)
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError):
        raise ErroNegocio("Arquivo de imagem inválido.")
    if img.mode != "RGB":
        fundo = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        fundo.paste(img, mask=img.split()[-1])
        img = fundo
    img.thumbnail((lado_maximo, lado_maximo))
    img.save(destino, "JPEG", quality=85, optimize=True)


def criar_app(banco: Banco, pasta_dados: Path, url_base_padrao="", impressao_sincrona: bool = False) -> Flask:
    """`url_base_padrao` pode ser um texto fixo ou uma função que devolve o
    endereço atual deste PC na rede (redescoberto se o IP mudar)."""
    web = Path(__file__).parent / "web"
    app = Flask(__name__, template_folder=str(web / "templates"), static_folder=str(web / "static"))
    app.secret_key = banco.secret_key()
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
    app.permanent_session_lifetime = timedelta(days=60)
    # Mantém a ordem definida no código (formas de pagamento, permissões):
    # por padrão o Flask ordenaria alfabeticamente ("Crédito" antes de "Dinheiro").
    app.json.sort_keys = False

    pasta_fotos = pasta_dados / "fotos"
    pasta_midias = pasta_dados / "midias"
    pasta_fotos.mkdir(parents=True, exist_ok=True)
    pasta_midias.mkdir(parents=True, exist_ok=True)

    def url_base() -> str:
        padrao = url_base_padrao() if callable(url_base_padrao) else url_base_padrao
        return (banco.config().get("url_base") or padrao or request.host_url).rstrip("/")

    @app.errorhandler(ErroNegocio)
    def erro_negocio(exc):
        return jsonify({"ok": False, "erro": str(exc)}), 400

    @app.after_request
    def sem_cache(resposta):
        # TVs e tablets raramente têm como forçar "recarregar sem cache":
        # sem isso uma versão antiga das telas ficaria presa após atualizar.
        if not request.path.startswith(("/foto/", "/midia/")):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    # --- Usuário logado e permissões ----------------------------------------

    def usuario_atual():
        if "usuario" not in g:
            uid = session.get("usuario_id")
            usuario = banco.obter_usuario(uid) if uid else None
            # Usuário desativado (ou excluído) perde o acesso na hora, mesmo logado.
            g.usuario = usuario if usuario and usuario["ativo"] else None
        return g.usuario

    def ator():
        u = usuario_atual()
        return {"id": u["id"], "nome": u["nome"]} if u else None

    def pode(*permissoes) -> bool:
        u = usuario_atual()
        return bool(u) and any(p in u["permissoes"] for p in permissoes)

    def exigir(*permissoes):
        """Exige login e, se informado, pelo menos uma das permissões."""
        def decorador(func):
            @wraps(func)
            def envoltorio(*args, **kwargs):
                api = request.path.startswith("/api/")
                if not banco.existe_usuario():
                    if api:
                        return jsonify({"ok": False, "erro": "Crie o administrador no primeiro acesso."}), 401
                    return redirect(url_for("primeiro_acesso"))
                if not usuario_atual():
                    if api:
                        return jsonify({"ok": False, "erro": "Faça login para continuar."}), 401
                    return redirect(url_for("login", proximo=request.path))
                if permissoes and not pode(*permissoes):
                    if api:
                        return jsonify({"ok": False, "erro": "Você não tem permissão para isso. Fale com o administrador."}), 403
                    return render_template("mensagem.html", titulo="Sem permissão",
                                           texto="Seu usuário não tem acesso a esta página. Fale com o administrador.",
                                           voltar=True), 403
                return func(*args, **kwargs)
            return envoltorio
        return decorador

    @app.context_processor
    def contexto_templates():
        return {"usuario": usuario_atual(), "pode": pode, "loja": banco.config()["nome_loja"]}

    # --- Login ---------------------------------------------------------------

    def _destino_seguro(proximo: str) -> str:
        return proximo if proximo and proximo.startswith("/") and not proximo.startswith("//") else "/"

    @app.get("/login")
    def login():
        if not banco.existe_usuario():
            return redirect(url_for("primeiro_acesso"))
        return render_template("login.html", erro=None)

    @app.post("/login")
    def login_post():
        usuario = banco.autenticar(request.form.get("usuario", ""), request.form.get("senha", ""))
        if not usuario:
            time.sleep(1)  # atrasa quem tenta adivinhar senhas
            return render_template("login.html", erro="Usuário ou senha incorretos."), 401
        session.clear()
        session.permanent = True
        session["usuario_id"] = usuario["id"]
        return redirect(_destino_seguro(request.args.get("proximo")))

    @app.get("/sair")
    def sair():
        if usuario_atual():
            banco.registrar_saida(ator())
        session.clear()
        return redirect(url_for("login"))

    @app.get("/primeiro-acesso")
    def primeiro_acesso():
        if banco.existe_usuario():
            return redirect(url_for("login"))
        return render_template("primeiro_acesso.html", erro=None)

    @app.post("/primeiro-acesso")
    def primeiro_acesso_post():
        if banco.existe_usuario():
            return redirect(url_for("login"))
        form = request.form
        if form.get("senha") != form.get("confirmar"):
            return render_template("primeiro_acesso.html", erro="As senhas não conferem."), 400
        try:
            usuario = banco.criar_primeiro_admin({"nome": form.get("nome"), "login": form.get("usuario"),
                                                  "senha": form.get("senha")})
        except ErroNegocio as exc:
            return render_template("primeiro_acesso.html", erro=str(exc)), 400
        session.clear()
        session.permanent = True
        session["usuario_id"] = usuario["id"]
        return redirect("/admin#usuarios")

    @app.get("/api/eu")
    @exigir()
    def api_eu():
        return jsonify({"usuario": usuario_atual()})

    @app.post("/api/minha-senha")
    @exigir()
    def api_minha_senha():
        dados = request.get_json(silent=True) or {}
        banco.trocar_propria_senha(ator(), dados.get("atual", ""), dados.get("nova", ""))
        return jsonify({"ok": True})

    # --- Telas ---------------------------------------------------------------

    @app.get("/")
    @exigir()
    def inicio():
        return render_template("inicio.html", url_base=url_base(), permissoes_admin=PERMISSOES_ADMIN)

    @app.get("/caixa")
    @exigir("pedidos", "receber", "caixa")
    def tela_caixa():
        return render_template("caixa.html")

    @app.get("/cozinha")
    @exigir("cozinha")
    def tela_cozinha():
        return render_template("cozinha.html")

    @app.get("/garcom")
    @exigir("garcom")
    def tela_garcom():
        return render_template("garcom.html")

    @app.get("/admin")
    @exigir(*PERMISSOES_ADMIN)
    def tela_admin():
        return render_template("admin.html")

    @app.get("/painel")
    def tela_painel():
        return render_template("painel.html")

    @app.get("/m/<token>")
    def tela_cliente(token):
        if not banco.mesa_por_token(token):
            return render_template("mensagem.html", titulo="QR code inválido",
                                   texto="Este QR code não é mais válido. Chame um atendente."), 404
        return render_template("cliente.html", token=token)

    # --- Arquivos ------------------------------------------------------------

    @app.get("/foto/<nome>")
    def foto(nome):
        return send_from_directory(pasta_fotos, nome, max_age=3600)

    @app.get("/midia/<nome>")
    def midia(nome):
        return send_from_directory(pasta_midias, nome, conditional=True, max_age=3600)

    # --- Estado para caixa/cozinha -------------------------------------------

    def _versao_igual() -> bool:
        return request.args.get("v") == str(banco.versao)

    @app.get("/api/estado")
    @exigir("pedidos", "garcom", "cozinha", "receber", "caixa")
    def api_estado():
        if _versao_igual():
            return jsonify({"versao": banco.versao, "mudou": False})
        cfg = banco.config()
        sessao = banco.sessao_aberta()
        dados = {
            "versao": banco.versao,
            "mudou": True,
            "loja": cfg["nome_loja"],
            "usuario": usuario_atual(),
            "pedidos": banco.listar_pedidos(),
            "chamados_garcom": banco.chamados_pendentes() if pode("pedidos", "garcom") else [],
            "produtos": banco.listar_produtos(somente_ativos=True) if pode("pedidos", "garcom") else [],
            "contas": banco.contas_abertas() if pode("pedidos", "receber", "garcom") else [],
            "mesas": [m["numero"] for m in banco.listar_mesas()] if pode("garcom") else [],
            "caixa_aberto": sessao is not None,
            "sessao": None,
            "recebimentos": [],
            "formas": FORMAS_PAGAMENTO,
            "taxa_servico_percentual": cfg["taxa_servico_percentual"],
            "impressora_cozinha_ativa": cfg["impressora_cozinha_ativa"],
            "impressora_caixa_ativa": cfg["impressora_caixa_ativa"],
        }
        if sessao and pode("caixa", "receber"):
            resumo = banco.resumo_sessao(sessao["id"])
            # Fechamento "cego": quem fecha o caixa conta o dinheiro sem saber
            # quanto deveria ter — o valor esperado só aparece depois de fechar
            # (e nos relatórios).
            resumo.pop("esperado_dinheiro", None)
            dados["sessao"] = resumo
            dados["recebimentos"] = banco.listar_recebimentos(sessao["id"])
        return jsonify(dados)

    # --- Impressão (em segundo plano: impressora lenta não trava a tela) ------

    def _imprimir(qual: str, gerar, ao_terminar=None) -> None:
        cfg = banco.config()
        if not cfg[f"impressora_{qual}_ativa"]:
            raise ErroNegocio(f"A impressora {'da cozinha' if qual == 'cozinha' else 'do caixa'} está desligada nas configurações.")

        def trabalho():
            try:
                impressora.enviar(cfg[f"impressora_{qual}_host"], cfg[f"impressora_{qual}_porta"],
                                  gerar(cfg["nome_loja"], cfg["impressora_colunas"], cfg["impressora_codificacao"]))
                resultado = "ok"
            except impressora.ErroImpressora as exc:
                log.warning("Falha na impressora %s: %s", qual, exc)
                resultado = f"erro: {exc}"
            if ao_terminar:
                ao_terminar(resultado)

        if impressao_sincrona:
            trabalho()
        else:
            threading.Thread(target=trabalho, daemon=True).start()

    def _imprimir_cozinha(pedido: dict) -> None:
        if not pedido["vai_cozinha"]:
            raise ErroNegocio("Esse pedido não tem nada para a cozinha preparar.")
        banco.registrar_impressao(pedido["id"], "imprimindo")
        _imprimir("cozinha", lambda loja, col, cod: impressora.cupom_cozinha(pedido, loja, col, cod),
                  lambda r: banco.registrar_impressao(pedido["id"], r))

    # --- Pedidos ---------------------------------------------------------------

    @app.post("/api/pedidos")
    @exigir("pedidos", "garcom")
    def api_criar_pedido():
        dados = request.get_json(silent=True) or {}
        origem = "garcom" if dados.get("origem") == "garcom" or not pode("pedidos") else "caixa"
        if origem == "garcom" and not pode("garcom"):
            return jsonify({"ok": False, "erro": "Você não tem permissão para isso. Fale com o administrador."}), 403
        if origem == "garcom" and not str(dados.get("mesa") or "").strip():
            raise ErroNegocio("Escolha a mesa do pedido.")
        pedido = banco.criar_pedido(dados.get("itens"), origem=origem, mesa=dados.get("mesa", ""),
                                    cliente=dados.get("cliente", ""), observacao=dados.get("observacao", ""), por=ator())
        if banco.config()["impressora_cozinha_ativa"] and pedido["vai_cozinha"]:
            _imprimir_cozinha(pedido)
        return jsonify({"ok": True, "pedido": banco.obter_pedido(pedido["id"])})

    @app.post("/api/pedidos/<int:pedido_id>/status")
    @exigir("pedidos", "garcom", "cozinha", "cancelar")
    def api_status(pedido_id):
        dados = request.get_json(silent=True) or {}
        status = dados.get("status")
        necessario = {"cancelado": ("cancelar",), "entregue": ("pedidos", "garcom")}.get(status, ("cozinha", "pedidos"))
        if not pode(*necessario):
            return jsonify({"ok": False, "erro": "Você não tem permissão para isso. Fale com o administrador."}), 403
        return jsonify({"ok": True, "pedido": banco.mudar_status(pedido_id, status, por=ator(), motivo=dados.get("motivo", ""))})

    @app.post("/api/pedidos/<int:pedido_id>/chamar")
    @exigir("pedidos")
    def api_chamar(pedido_id):
        return jsonify({"ok": True, "pedido": banco.chamar(pedido_id, por=ator())})

    @app.post("/api/pedidos/<int:pedido_id>/imprimir")
    @exigir("pedidos")
    def api_reimprimir(pedido_id):
        pedido = banco.obter_pedido(pedido_id)
        if not pedido:
            abort(404)
        _imprimir_cozinha(pedido)
        banco.registrar_acao(ator(), "Reimprimiu pedido na cozinha", f"Pedido nº {pedido['codigo']}", pedido_id)
        return jsonify({"ok": True})

    @app.post("/api/garcom/<int:chamado_id>/atender")
    @exigir("pedidos", "garcom")
    def api_atender_chamado(chamado_id):
        banco.atender_chamado(chamado_id, por=ator())
        return jsonify({"ok": True})

    @app.post("/api/contas/imprimir")
    @exigir("pedidos", "receber", "garcom")
    def api_imprimir_conta():
        dados = request.get_json(silent=True) or {}
        pedidos = [banco.obter_pedido(int(i)) for i in dados.get("pedido_ids") or []]
        pedidos = [p for p in pedidos if p and p["status"] != "cancelado"]
        if not pedidos:
            raise ErroNegocio("Nada para imprimir.")
        titulo = str(dados.get("titulo") or "")[:60]
        taxa = banco.config()["taxa_servico_percentual"]
        _imprimir("caixa", lambda loja, col, cod: impressora.cupom_conta(titulo, pedidos, loja, taxa, col, cod))
        banco.registrar_acao(ator(), "Imprimiu conferência de conta", titulo)
        return jsonify({"ok": True})

    # --- Caixa e pagamentos --------------------------------------------------

    @app.post("/api/caixa/abrir")
    @exigir("caixa")
    def api_abrir_caixa():
        dados = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "sessao": banco.abrir_caixa(dados.get("valor_abertura", 0), ator())})

    @app.post("/api/caixa/movimento")
    @exigir("caixa")
    def api_movimento():
        dados = request.get_json(silent=True) or {}
        banco.movimentar_caixa(dados.get("tipo"), dados.get("valor"), dados.get("motivo", ""), ator())
        return jsonify({"ok": True})

    def _imprimir_fechamento(resumo: dict) -> None:
        _imprimir("caixa", lambda loja, col, cod: impressora.cupom_fechamento(resumo, loja, FORMAS_PAGAMENTO, col, cod))

    @app.post("/api/caixa/fechar")
    @exigir("caixa")
    def api_fechar_caixa():
        dados = request.get_json(silent=True) or {}
        resumo = banco.fechar_caixa(dados.get("valor_contado"), dados.get("observacao", ""), ator())
        impresso = False
        if banco.config()["impressora_caixa_ativa"]:
            _imprimir_fechamento(resumo)
            impresso = True
        return jsonify({"ok": True, "sessao": resumo, "impresso": impresso})

    @app.get("/api/caixa/sessoes/<int:sessao_id>")
    @exigir("caixa", "relatorios")
    def api_sessao(sessao_id):
        return jsonify({"sessao": banco.resumo_sessao(sessao_id)})

    @app.post("/api/caixa/sessoes/<int:sessao_id>/imprimir")
    @exigir("caixa", "relatorios")
    def api_imprimir_sessao(sessao_id):
        _imprimir_fechamento(banco.resumo_sessao(sessao_id))
        banco.registrar_acao(ator(), "Reimprimiu fechamento de caixa", f"Caixa nº {sessao_id}")
        return jsonify({"ok": True})

    @app.post("/api/recebimentos")
    @exigir("receber")
    def api_receber():
        dados = request.get_json(silent=True) or {}
        rec = banco.receber(dados.get("pedido_ids"), dados.get("formas"), ator(),
                            desconto=dados.get("desconto", 0), acrescimo=dados.get("acrescimo", 0))
        return jsonify({"ok": True, "recebimento": rec})

    @app.post("/api/recebimentos/<int:rid>/estornar")
    @exigir("estornar")
    def api_estornar(rid):
        banco.estornar_recebimento(rid, (request.get_json(silent=True) or {}).get("motivo", ""), ator())
        return jsonify({"ok": True})

    # --- Cliente (QR code da mesa) — público, identificado pelo token ---------

    def _mesa_ou_404(token):
        mesa = banco.mesa_por_token(token)
        if not mesa:
            abort(404)
        return mesa

    def _pedido_para_cliente(p: dict) -> dict:
        return {k: p[k] for k in ("id", "codigo", "status", "itens", "total_centavos", "criado_em", "cliente", "pago")}

    @app.get("/api/cliente/<token>")
    def api_cliente(token):
        mesa = _mesa_ou_404(token)
        cfg = banco.config()
        return jsonify({
            "versao": banco.versao,
            "loja": cfg["nome_loja"],
            "mesa": mesa["numero"],
            "pedidos_ativos": cfg["pedidos_qrcode_ativo"],
            "produtos": banco.listar_produtos(somente_ativos=True),
            "pedidos": [_pedido_para_cliente(p) for p in banco.listar_pedidos(
                statuses=("novo", "preparando", "pronto", "chamado", "entregue"), mesa=mesa["numero"])],
            "chamados": [c["tipo"] for c in banco.chamados_pendentes(mesa["numero"])],
        })

    @app.post("/api/cliente/<token>/pedido")
    def api_cliente_pedido(token):
        mesa = _mesa_ou_404(token)
        cfg = banco.config()
        if not cfg["pedidos_qrcode_ativo"]:
            raise ErroNegocio("Pedidos pelo QR code estão desativados no momento. Chame um atendente.")
        dados = request.get_json(silent=True) or {}
        pedido = banco.criar_pedido(
            dados.get("itens"), origem="qrcode", mesa=mesa["numero"],
            cliente=dados.get("cliente", ""), observacao=dados.get("observacao", ""),
            por={"id": None, "nome": f"Cliente (mesa {mesa['numero']})"},
        )
        if cfg["impressora_cozinha_ativa"] and pedido["vai_cozinha"]:
            _imprimir_cozinha(pedido)
        return jsonify({"ok": True, "pedido": _pedido_para_cliente(pedido)})

    @app.post("/api/cliente/<token>/chamar")
    def api_cliente_chamar(token):
        mesa = _mesa_ou_404(token)
        banco.chamar_garcom(mesa["numero"], (request.get_json(silent=True) or {}).get("tipo", "garcom"))
        return jsonify({"ok": True})

    # --- Painel de chamada (TV) — público, só leitura ------------------------

    @app.get("/api/painel")
    def api_painel():
        if _versao_igual():
            return jsonify({"versao": banco.versao, "mudou": False})
        cfg = banco.config()
        chamadas = banco.chamadas_recentes(cfg["historico_painel"] + 1)
        if not cfg["mostrar_nome_cliente_painel"]:
            for c in chamadas:
                c["cliente"] = ""
        return jsonify({
            "versao": banco.versao,
            "mudou": True,
            "loja": cfg["nome_loja"],
            "som": cfg["som_chamada"],
            "voz": cfg["voz_chamada"],
            "duracao_foto": cfg["duracao_foto_painel"],
            "chamadas": chamadas,
            "midias": [{"url": f"/midia/{m['arquivo']}", "tipo": m["tipo"], "duracao": m["duracao"]}
                       for m in banco.listar_midias(somente_ativas=True)],
            # Sem mídia cadastrada, o painel mostra os próprios produtos com foto.
            "produtos": [{"nome": p["nome"], "preco_centavos": p["preco_centavos"], "foto": f"/foto/{p['foto']}"}
                         for p in banco.listar_produtos(somente_ativos=True) if p["foto"]],
        })

    # --- Administração: produtos ---------------------------------------------

    @app.get("/api/produtos")
    @exigir("cardapio")
    def api_produtos():
        return jsonify({"produtos": banco.listar_produtos()})

    @app.post("/api/produtos")
    @exigir("cardapio")
    def api_criar_produto():
        return jsonify({"ok": True, "produto": banco.criar_produto(request.get_json(silent=True) or {}, por=ator())})

    @app.put("/api/produtos/<int:produto_id>")
    @exigir("cardapio")
    def api_atualizar_produto(produto_id):
        return jsonify({"ok": True, "produto": banco.atualizar_produto(produto_id, request.get_json(silent=True) or {}, por=ator())})

    @app.post("/api/produtos/categoria-cozinha")
    @exigir("cardapio")
    def api_categoria_cozinha():
        dados = request.get_json(silent=True) or {}
        categoria = str(dados.get("categoria") or "")
        if not categoria:
            raise ErroNegocio("Categoria inválida.")
        alterados = banco.definir_cozinha_categoria(categoria, bool(dados.get("vai_cozinha")), por=ator())
        return jsonify({"ok": True, "alterados": alterados})

    @app.delete("/api/produtos/<int:produto_id>")
    @exigir("cardapio")
    def api_excluir_produto(produto_id):
        foto_antiga = banco.excluir_produto(produto_id, por=ator())
        if foto_antiga:
            (pasta_fotos / foto_antiga).unlink(missing_ok=True)
        return jsonify({"ok": True})

    @app.post("/api/produtos/<int:produto_id>/foto")
    @exigir("cardapio")
    def api_foto_produto(produto_id):
        produto = banco.obter_produto(produto_id)
        if not produto:
            abort(404)
        enviado = request.files.get("arquivo")
        if not enviado or Path(enviado.filename or "").suffix.lower() not in EXT_FOTO:
            raise ErroNegocio("Envie uma imagem (JPG, PNG, WEBP...).")
        nome = f"produto-{produto_id}-{uuid.uuid4().hex[:8]}.jpg"
        _salvar_foto(enviado, pasta_fotos / nome, 900)
        banco.definir_foto_produto(produto_id, nome, por=ator())
        if produto["foto"]:
            (pasta_fotos / produto["foto"]).unlink(missing_ok=True)
        return jsonify({"ok": True, "produto": banco.obter_produto(produto_id)})

    @app.delete("/api/produtos/<int:produto_id>/foto")
    @exigir("cardapio")
    def api_remover_foto_produto(produto_id):
        produto = banco.obter_produto(produto_id)
        if not produto:
            abort(404)
        banco.definir_foto_produto(produto_id, None, por=ator())
        if produto["foto"]:
            (pasta_fotos / produto["foto"]).unlink(missing_ok=True)
        return jsonify({"ok": True})

    # --- Administração: mesas e QR codes -------------------------------------

    def _mesa_com_link(mesa: dict) -> dict:
        return {**mesa, "link": f"{url_base()}/m/{mesa['token']}"}

    @app.get("/api/mesas")
    @exigir("mesas")
    def api_mesas():
        return jsonify({"mesas": [_mesa_com_link(m) for m in banco.listar_mesas()], "url_base": url_base()})

    @app.post("/api/mesas")
    @exigir("mesas")
    def api_criar_mesas():
        dados = request.get_json(silent=True) or {}
        if dados.get("ate"):
            try:
                criadas = banco.criar_mesas_em_lote(int(dados.get("de") or 1), int(dados["ate"]), por=ator())
            except (TypeError, ValueError):
                raise ErroNegocio("Intervalo de mesas inválido.")
        else:
            banco.criar_mesa(dados.get("numero"), por=ator())
            criadas = 1
        return jsonify({"ok": True, "criadas": criadas})

    @app.post("/api/mesas/<int:mesa_id>/novo-qrcode")
    @exigir("mesas")
    def api_novo_qrcode(mesa_id):
        return jsonify({"ok": True, "mesa": _mesa_com_link(banco.novo_token_mesa(mesa_id, por=ator()))})

    @app.delete("/api/mesas/<int:mesa_id>")
    @exigir("mesas")
    def api_excluir_mesa(mesa_id):
        banco.excluir_mesa(mesa_id, por=ator())
        return jsonify({"ok": True})

    @app.get("/qrcode/mesa/<int:mesa_id>.svg")
    @exigir("mesas")
    def qrcode_mesa(mesa_id):
        mesa = banco.obter_mesa(mesa_id)
        if not mesa:
            abort(404)
        buf = io.BytesIO()
        segno.make(_mesa_com_link(mesa)["link"], error="m").save(buf, kind="svg", scale=10, border=2)
        return app.response_class(buf.getvalue(), mimetype="image/svg+xml")

    @app.get("/admin/qrcodes")
    @exigir("mesas")
    def imprimir_qrcodes():
        return render_template("qrcodes.html", mesas=[_mesa_com_link(m) for m in banco.listar_mesas()])

    # --- Administração: mídias do painel -------------------------------------

    @app.get("/api/midias")
    @exigir("midias")
    def api_midias():
        return jsonify({"midias": banco.listar_midias()})

    @app.post("/api/midias")
    @exigir("midias")
    def api_enviar_midias():
        enviados = request.files.getlist("arquivos")
        if not enviados:
            raise ErroNegocio("Nenhum arquivo enviado.")
        adicionadas, recusados = 0, []
        for enviado in enviados:
            ext = Path(enviado.filename or "").suffix.lower()
            if ext in EXT_FOTO:
                nome = f"{uuid.uuid4().hex}.jpg"
                try:
                    _salvar_foto(enviado, pasta_midias / nome, 1920)
                except ErroNegocio:
                    recusados.append(enviado.filename)
                    continue
                banco.adicionar_midia(nome, "foto", enviado.filename, por=ator())
            elif ext in EXT_VIDEO:
                nome = f"{uuid.uuid4().hex}{ext}"
                enviado.save(pasta_midias / nome)
                banco.adicionar_midia(nome, "video", enviado.filename, por=ator())
            else:
                recusados.append(enviado.filename)
                continue
            adicionadas += 1
        return jsonify({"ok": True, "adicionadas": adicionadas, "recusados": recusados})

    @app.put("/api/midias/<int:midia_id>")
    @exigir("midias")
    def api_atualizar_midia(midia_id):
        dados = request.get_json(silent=True) or {}
        if "mover" in dados:
            banco.mover_midia(midia_id, int(dados["mover"]), por=ator())
        else:
            banco.atualizar_midia(midia_id, dados, por=ator())
        return jsonify({"ok": True})

    @app.delete("/api/midias/<int:midia_id>")
    @exigir("midias")
    def api_excluir_midia(midia_id):
        arquivo = banco.excluir_midia(midia_id, por=ator())
        if arquivo:
            (pasta_midias / arquivo).unlink(missing_ok=True)
        return jsonify({"ok": True})

    # --- Administração: configurações ----------------------------------------

    @app.get("/api/config")
    @exigir("configuracoes")
    def api_config():
        padrao = url_base_padrao() if callable(url_base_padrao) else url_base_padrao
        return jsonify({"config": banco.config_publica(), "url_base_detectada": padrao})

    @app.put("/api/config")
    @exigir("configuracoes")
    def api_salvar_config():
        dados = dict(request.get_json(silent=True) or {})
        dados.pop("secret_key", None)
        banco.salvar_config(dados, por=ator())
        return jsonify({"ok": True, "config": banco.config_publica()})

    @app.post("/api/impressora/teste")
    @exigir("configuracoes")
    def api_teste_impressora():
        qual = (request.get_json(silent=True) or {}).get("qual", "cozinha")
        if qual not in ("cozinha", "caixa"):
            raise ErroNegocio("Impressora inválida.")
        cfg = banco.config()
        cupom = impressora.Cupom(cfg["impressora_colunas"], cfg["impressora_codificacao"])
        cupom.cmd(impressora.ALINHAR_CENTRO).linha(cfg["nome_loja"])
        cupom.cmd(impressora.TAMANHO_DUPLO).linha("TESTE OK").cmd(impressora.TAMANHO_NORMAL)
        cupom.linha(f"Impressora do(a) {qual}").linha("Acentuação: ção ã é ê ó ú ç")
        cupom.separador()
        try:
            impressora.enviar(cfg[f"impressora_{qual}_host"], cfg[f"impressora_{qual}_porta"], cupom.bytes())
        except impressora.ErroImpressora as exc:
            raise ErroNegocio(str(exc))
        return jsonify({"ok": True})

    # --- Administração: usuários e permissões --------------------------------

    @app.get("/api/usuarios")
    @exigir("usuarios")
    def api_usuarios():
        return jsonify({
            "usuarios": banco.listar_usuarios(),
            "permissoes": PERMISSOES,
            "modelos": {k: {"nome": nome, "permissoes": perms} for k, (nome, perms) in MODELOS.items()},
        })

    @app.post("/api/usuarios")
    @exigir("usuarios")
    def api_criar_usuario():
        return jsonify({"ok": True, "usuario": banco.criar_usuario(request.get_json(silent=True) or {}, por=ator())})

    @app.put("/api/usuarios/<int:usuario_id>")
    @exigir("usuarios")
    def api_atualizar_usuario(usuario_id):
        return jsonify({"ok": True, "usuario": banco.atualizar_usuario(usuario_id, request.get_json(silent=True) or {}, por=ator())})

    # --- Relatórios e histórico ----------------------------------------------

    def _periodo_args():
        hoje = datetime.now().strftime("%Y-%m-%d")
        return request.args.get("de") or hoje, request.args.get("ate") or hoje

    @app.get("/api/relatorios")
    @exigir("relatorios")
    def api_relatorio():
        de, ate = _periodo_args()
        return jsonify({"relatorio": banco.relatorio(de, ate), "formas": FORMAS_PAGAMENTO})

    @app.get("/api/relatorios/vendas.csv")
    @exigir("relatorios")
    def api_vendas_csv():
        de, ate = _periodo_args()
        banco.registrar_acao(ator(), "Exportou planilha de vendas", f"{de} a {ate}")
        return Response(banco.vendas_csv(de, ate), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=vendas_{de}_a_{ate}.csv"})

    @app.get("/api/auditoria")
    @exigir("historico")
    def api_auditoria():
        de, ate = _periodo_args()
        return jsonify({
            "registros": banco.listar_auditoria(de, ate, request.args.get("usuario_id") or None,
                                                request.args.get("busca", "").strip()),
            "usuarios": [{"id": u["id"], "nome": u["nome"]} for u in banco.listar_usuarios()],
        })

    return app


def rodar(app: Flask, host: str, porta: int) -> None:
    from waitress import serve
    # Várias telas consultando a cada ~2 s, mais vídeos do painel em
    # streaming: threads de sobra pra nenhuma tela travar esperando.
    serve(app, host=host, port=porta, threads=32, channel_timeout=60)
