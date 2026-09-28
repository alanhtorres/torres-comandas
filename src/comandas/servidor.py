"""Servidor web: telas (caixa, cozinha, painel, cliente via QR code, totem de
senhas, administração) e a API que todas elas usam."""
import io
import logging
import threading
import time
import uuid
from datetime import timedelta
from functools import wraps
from pathlib import Path

import segno
from flask import (
    Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash

from . import impressora
from .banco import PREFIXOS_SENHA, Banco, ErroNegocio

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


def criar_app(banco: Banco, pasta_dados: Path, url_base_padrao: str = "", impressao_sincrona: bool = False) -> Flask:
    web = Path(__file__).parent / "web"
    app = Flask(__name__, template_folder=str(web / "templates"), static_folder=str(web / "static"))
    app.secret_key = banco.secret_key()
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
    app.permanent_session_lifetime = timedelta(days=60)

    pasta_fotos = pasta_dados / "fotos"
    pasta_midias = pasta_dados / "midias"
    pasta_fotos.mkdir(parents=True, exist_ok=True)
    pasta_midias.mkdir(parents=True, exist_ok=True)

    @app.errorhandler(ErroNegocio)
    def erro_negocio(exc):
        return jsonify({"ok": False, "erro": str(exc)}), 400

    @app.after_request
    def sem_cache(resposta):
        # TVs e totens raramente têm como forçar "recarregar sem cache":
        # sem isso uma versão antiga das telas ficaria presa após atualizar.
        if not request.path.startswith(("/foto/", "/midia/")):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    # --- Acesso da equipe (PIN) ---------------------------------------------

    def pin_definido() -> bool:
        return bool(banco.config().get("pin_hash"))

    def equipe_logada() -> bool:
        return not pin_definido() or bool(session.get("equipe"))

    def exigir_equipe(func):
        @wraps(func)
        def envoltorio(*args, **kwargs):
            if equipe_logada():
                return func(*args, **kwargs)
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "erro": "Acesso restrito: faça login com o PIN."}), 401
            return redirect(url_for("login", proximo=request.path))
        return envoltorio

    @app.get("/login")
    def login():
        return render_template("login.html", loja=banco.config()["nome_loja"], erro=None)

    @app.post("/login")
    def login_post():
        cfg = banco.config()
        proximo = request.args.get("proximo") or "/"
        if not proximo.startswith("/") or proximo.startswith("//"):
            proximo = "/"
        if not cfg.get("pin_hash") or check_password_hash(cfg["pin_hash"], request.form.get("pin", "")):
            session.permanent = True
            session["equipe"] = True
            return redirect(proximo)
        time.sleep(1)  # atrasa tentativas de adivinhar o PIN
        return render_template("login.html", loja=cfg["nome_loja"], erro="PIN incorreto."), 401

    @app.get("/sair")
    def sair():
        session.clear()
        return redirect(url_for("login"))

    # --- Telas ---------------------------------------------------------------

    def url_base() -> str:
        return (banco.config().get("url_base") or url_base_padrao or request.host_url).rstrip("/")

    @app.get("/")
    @exigir_equipe
    def inicio():
        return render_template("inicio.html", loja=banco.config()["nome_loja"], url_base=url_base())

    @app.get("/caixa")
    @exigir_equipe
    def tela_caixa():
        return render_template("caixa.html")

    @app.get("/cozinha")
    @exigir_equipe
    def tela_cozinha():
        return render_template("cozinha.html")

    @app.get("/totem")
    @exigir_equipe
    def tela_totem():
        return render_template("totem.html")

    @app.get("/admin")
    @exigir_equipe
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
    @exigir_equipe
    def api_estado():
        if _versao_igual():
            return jsonify({"versao": banco.versao, "mudou": False})
        cfg = banco.config()
        return jsonify({
            "versao": banco.versao,
            "mudou": True,
            "loja": cfg["nome_loja"],
            "pedidos": banco.listar_pedidos(tipo="pedido"),
            "senhas": banco.resumo_senhas(),
            "senhas_chamadas": banco.listar_pedidos(statuses=("chamado",), tipo="senha"),
            "chamados_garcom": banco.chamados_pendentes(),
            "produtos": banco.listar_produtos(somente_ativos=True),
            "impressora_cozinha_ativa": cfg["impressora_cozinha_ativa"],
        })

    # --- Pedidos ---------------------------------------------------------------

    def _imprimir_cozinha(pedido: dict) -> None:
        cfg = banco.config()
        if not cfg["impressora_cozinha_ativa"]:
            return

        def trabalho():
            try:
                dados = impressora.cupom_cozinha(pedido, cfg["nome_loja"], cfg["impressora_colunas"],
                                                 cfg["impressora_codificacao"])
                impressora.enviar(cfg["impressora_cozinha_host"], cfg["impressora_cozinha_porta"], dados)
                banco.registrar_impressao(pedido["id"], "ok")
            except impressora.ErroImpressora as exc:
                log.warning("Pedido %s não impresso: %s", pedido["codigo"], exc)
                banco.registrar_impressao(pedido["id"], f"erro: {exc}")

        banco.registrar_impressao(pedido["id"], "imprimindo")
        if impressao_sincrona:
            trabalho()
        else:
            threading.Thread(target=trabalho, daemon=True).start()

    def _imprimir_senha(senha: dict) -> None:
        cfg = banco.config()
        if not cfg["impressora_senhas_ativa"]:
            return

        def trabalho():
            try:
                dados = impressora.cupom_senha(senha, cfg["nome_loja"], PREFIXOS_SENHA[senha["prefixo"]],
                                               cfg["impressora_colunas"], cfg["impressora_codificacao"])
                impressora.enviar(cfg["impressora_senhas_host"], cfg["impressora_senhas_porta"], dados)
                banco.registrar_impressao(senha["id"], "ok")
            except impressora.ErroImpressora as exc:
                log.warning("Senha %s não impressa: %s", senha["codigo"], exc)
                banco.registrar_impressao(senha["id"], f"erro: {exc}")

        if impressao_sincrona:
            trabalho()
        else:
            threading.Thread(target=trabalho, daemon=True).start()

    @app.post("/api/pedidos")
    @exigir_equipe
    def api_criar_pedido():
        dados = request.get_json(silent=True) or {}
        pedido = banco.criar_pedido(
            dados.get("itens"), origem="caixa", mesa=dados.get("mesa", ""),
            cliente=dados.get("cliente", ""), observacao=dados.get("observacao", ""),
        )
        _imprimir_cozinha(pedido)
        return jsonify({"ok": True, "pedido": banco.obter_pedido(pedido["id"])})

    @app.post("/api/pedidos/<int:pedido_id>/status")
    @exigir_equipe
    def api_status(pedido_id):
        status = (request.get_json(silent=True) or {}).get("status")
        return jsonify({"ok": True, "pedido": banco.mudar_status(pedido_id, status)})

    @app.post("/api/pedidos/<int:pedido_id>/chamar")
    @exigir_equipe
    def api_chamar(pedido_id):
        guiche = (request.get_json(silent=True) or {}).get("guiche", "")
        return jsonify({"ok": True, "pedido": banco.chamar(pedido_id, guiche)})

    @app.post("/api/pedidos/<int:pedido_id>/imprimir")
    @exigir_equipe
    def api_reimprimir(pedido_id):
        pedido = banco.obter_pedido(pedido_id)
        if not pedido:
            abort(404)
        if not banco.config()["impressora_cozinha_ativa"]:
            raise ErroNegocio("A impressora da cozinha está desligada nas configurações.")
        _imprimir_cozinha(pedido)
        return jsonify({"ok": True})

    # --- Senhas ------------------------------------------------------------

    @app.post("/api/senhas")
    @exigir_equipe
    def api_emitir_senha():
        dados = request.get_json(silent=True) or {}
        origem = "totem" if dados.get("origem") == "totem" else "caixa"
        senha = banco.emitir_senha(dados.get("prefixo", "N"), origem=origem)
        _imprimir_senha(senha)
        return jsonify({"ok": True, "senha": senha, "impressa": banco.config()["impressora_senhas_ativa"]})

    @app.post("/api/senhas/chamar-proxima")
    @exigir_equipe
    def api_chamar_proxima():
        guiche = (request.get_json(silent=True) or {}).get("guiche", "")
        senha = banco.chamar_proxima_senha(guiche)
        if not senha:
            return jsonify({"ok": False, "erro": "Nenhuma senha aguardando."})
        return jsonify({"ok": True, "senha": senha})

    # --- Chamados de garçom -------------------------------------------------

    @app.post("/api/garcom/<int:chamado_id>/atender")
    @exigir_equipe
    def api_atender_chamado(chamado_id):
        banco.atender_chamado(chamado_id)
        return jsonify({"ok": True})

    # --- Cliente (QR code da mesa) — público, identificado pelo token ---------

    def _mesa_ou_404(token):
        mesa = banco.mesa_por_token(token)
        if not mesa:
            abort(404)
        return mesa

    def _pedido_para_cliente(p: dict) -> dict:
        return {k: p[k] for k in ("id", "codigo", "status", "itens", "total_centavos", "criado_em", "cliente")}

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
                statuses=("novo", "preparando", "pronto", "chamado", "entregue"), tipo="pedido", mesa=mesa["numero"])],
            "chamados": [c["tipo"] for c in banco.chamados_pendentes(mesa["numero"])],
        })

    @app.post("/api/cliente/<token>/pedido")
    def api_cliente_pedido(token):
        mesa = _mesa_ou_404(token)
        if not banco.config()["pedidos_qrcode_ativo"]:
            raise ErroNegocio("Pedidos pelo QR code estão desativados no momento. Chame um atendente.")
        dados = request.get_json(silent=True) or {}
        pedido = banco.criar_pedido(
            dados.get("itens"), origem="qrcode", mesa=mesa["numero"],
            cliente=dados.get("cliente", ""), observacao=dados.get("observacao", ""),
        )
        _imprimir_cozinha(pedido)
        return jsonify({"ok": True, "pedido": _pedido_para_cliente(pedido)})

    @app.post("/api/cliente/<token>/chamar")
    def api_cliente_chamar(token):
        mesa = _mesa_ou_404(token)
        tipo = (request.get_json(silent=True) or {}).get("tipo", "garcom")
        banco.chamar_garcom(mesa["numero"], tipo)
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
    @exigir_equipe
    def api_produtos():
        return jsonify({"produtos": banco.listar_produtos()})

    @app.post("/api/produtos")
    @exigir_equipe
    def api_criar_produto():
        return jsonify({"ok": True, "produto": banco.criar_produto(request.get_json(silent=True) or {})})

    @app.put("/api/produtos/<int:produto_id>")
    @exigir_equipe
    def api_atualizar_produto(produto_id):
        return jsonify({"ok": True, "produto": banco.atualizar_produto(produto_id, request.get_json(silent=True) or {})})

    @app.delete("/api/produtos/<int:produto_id>")
    @exigir_equipe
    def api_excluir_produto(produto_id):
        foto_antiga = banco.excluir_produto(produto_id)
        if foto_antiga:
            (pasta_fotos / foto_antiga).unlink(missing_ok=True)
        return jsonify({"ok": True})

    @app.post("/api/produtos/<int:produto_id>/foto")
    @exigir_equipe
    def api_foto_produto(produto_id):
        produto = banco.obter_produto(produto_id)
        if not produto:
            abort(404)
        enviado = request.files.get("arquivo")
        if not enviado or Path(enviado.filename or "").suffix.lower() not in EXT_FOTO:
            raise ErroNegocio("Envie uma imagem (JPG, PNG, WEBP...).")
        nome = f"produto-{produto_id}-{uuid.uuid4().hex[:8]}.jpg"
        _salvar_foto(enviado, pasta_fotos / nome, 900)
        banco.definir_foto_produto(produto_id, nome)
        if produto["foto"]:
            (pasta_fotos / produto["foto"]).unlink(missing_ok=True)
        return jsonify({"ok": True, "produto": banco.obter_produto(produto_id)})

    @app.delete("/api/produtos/<int:produto_id>/foto")
    @exigir_equipe
    def api_remover_foto_produto(produto_id):
        produto = banco.obter_produto(produto_id)
        if not produto:
            abort(404)
        banco.definir_foto_produto(produto_id, None)
        if produto["foto"]:
            (pasta_fotos / produto["foto"]).unlink(missing_ok=True)
        return jsonify({"ok": True})

    # --- Administração: mesas e QR codes -------------------------------------

    def _mesa_com_link(mesa: dict) -> dict:
        return {**mesa, "link": f"{url_base()}/m/{mesa['token']}"}

    @app.get("/api/mesas")
    @exigir_equipe
    def api_mesas():
        return jsonify({"mesas": [_mesa_com_link(m) for m in banco.listar_mesas()], "url_base": url_base()})

    @app.post("/api/mesas")
    @exigir_equipe
    def api_criar_mesas():
        dados = request.get_json(silent=True) or {}
        if dados.get("ate"):
            try:
                criadas = banco.criar_mesas_em_lote(int(dados.get("de") or 1), int(dados["ate"]))
            except (TypeError, ValueError):
                raise ErroNegocio("Intervalo de mesas inválido.")
        else:
            criadas = [banco.criar_mesa(dados.get("numero"))]
        return jsonify({"ok": True, "criadas": len(criadas)})

    @app.post("/api/mesas/<int:mesa_id>/novo-qrcode")
    @exigir_equipe
    def api_novo_qrcode(mesa_id):
        return jsonify({"ok": True, "mesa": _mesa_com_link(banco.novo_token_mesa(mesa_id))})

    @app.delete("/api/mesas/<int:mesa_id>")
    @exigir_equipe
    def api_excluir_mesa(mesa_id):
        banco.excluir_mesa(mesa_id)
        return jsonify({"ok": True})

    @app.get("/qrcode/mesa/<int:mesa_id>.svg")
    @exigir_equipe
    def qrcode_mesa(mesa_id):
        mesa = banco.obter_mesa(mesa_id)
        if not mesa:
            abort(404)
        buf = io.BytesIO()
        segno.make(_mesa_com_link(mesa)["link"], error="m").save(buf, kind="svg", scale=10, border=2)
        return app.response_class(buf.getvalue(), mimetype="image/svg+xml")

    @app.get("/admin/qrcodes")
    @exigir_equipe
    def imprimir_qrcodes():
        mesas = [_mesa_com_link(m) for m in banco.listar_mesas()]
        return render_template("qrcodes.html", mesas=mesas, loja=banco.config()["nome_loja"])

    # --- Administração: mídias do painel -------------------------------------

    @app.get("/api/midias")
    @exigir_equipe
    def api_midias():
        return jsonify({"midias": banco.listar_midias()})

    @app.post("/api/midias")
    @exigir_equipe
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
                banco.adicionar_midia(nome, "foto", enviado.filename)
            elif ext in EXT_VIDEO:
                nome = f"{uuid.uuid4().hex}{ext}"
                enviado.save(pasta_midias / nome)
                banco.adicionar_midia(nome, "video", enviado.filename)
            else:
                recusados.append(enviado.filename)
                continue
            adicionadas += 1
        return jsonify({"ok": True, "adicionadas": adicionadas, "recusados": recusados})

    @app.put("/api/midias/<int:midia_id>")
    @exigir_equipe
    def api_atualizar_midia(midia_id):
        dados = request.get_json(silent=True) or {}
        if "mover" in dados:
            banco.mover_midia(midia_id, int(dados["mover"]))
        else:
            banco.atualizar_midia(midia_id, dados)
        return jsonify({"ok": True})

    @app.delete("/api/midias/<int:midia_id>")
    @exigir_equipe
    def api_excluir_midia(midia_id):
        arquivo = banco.excluir_midia(midia_id)
        if arquivo:
            (pasta_midias / arquivo).unlink(missing_ok=True)
        return jsonify({"ok": True})

    # --- Administração: configurações ----------------------------------------

    @app.get("/api/config")
    @exigir_equipe
    def api_config():
        return jsonify({"config": banco.config_publica(), "url_base_detectada": url_base_padrao})

    @app.put("/api/config")
    @exigir_equipe
    def api_salvar_config():
        dados = dict(request.get_json(silent=True) or {})
        novo_pin = dados.pop("novo_pin", None)
        remover_pin = dados.pop("remover_pin", False)
        for chave in ("pin_hash", "secret_key"):
            dados.pop(chave, None)
        if novo_pin:
            novo_pin = str(novo_pin).strip()
            if not novo_pin.isdigit() or not 4 <= len(novo_pin) <= 12:
                raise ErroNegocio("O PIN deve ter de 4 a 12 números.")
            dados["pin_hash"] = generate_password_hash(novo_pin)
            session.permanent = True
            session["equipe"] = True  # quem definiu o PIN continua logado
        elif remover_pin:
            dados["pin_hash"] = ""
        banco.salvar_config(dados)
        return jsonify({"ok": True, "config": banco.config_publica()})

    @app.post("/api/impressora/teste")
    @exigir_equipe
    def api_teste_impressora():
        qual = (request.get_json(silent=True) or {}).get("qual", "cozinha")
        if qual not in ("cozinha", "senhas"):
            raise ErroNegocio("Impressora inválida.")
        cfg = banco.config()
        cupom = impressora.Cupom(cfg["impressora_colunas"], cfg["impressora_codificacao"])
        cupom.cmd(impressora.ALINHAR_CENTRO).linha(cfg["nome_loja"])
        cupom.cmd(impressora.TAMANHO_DUPLO).linha("TESTE OK").cmd(impressora.TAMANHO_NORMAL)
        cupom.linha(f"Impressora de {qual}").linha("Acentuação: ção ã é ê ó ú ç")
        cupom.separador()
        try:
            impressora.enviar(cfg[f"impressora_{qual}_host"], cfg[f"impressora_{qual}_porta"], cupom.bytes())
        except impressora.ErroImpressora as exc:
            raise ErroNegocio(str(exc))
        return jsonify({"ok": True})

    return app


def rodar(app: Flask, host: str, porta: int) -> None:
    from waitress import serve
    # Várias telas consultando a cada ~2 s, mais vídeos do painel em
    # streaming: threads de sobra pra nenhuma tela travar esperando.
    serve(app, host=host, port=porta, threads=32, channel_timeout=60)
