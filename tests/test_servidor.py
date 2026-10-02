import io

import pytest
from PIL import Image

from comandas.banco import Banco
from comandas.servidor import criar_app


@pytest.fixture
def ambiente(tmp_path):
    banco = Banco(tmp_path / "t.db")
    app = criar_app(banco, tmp_path, url_base_padrao=lambda: "http://192.168.0.10:8090", impressao_sincrona=True)
    return app, banco, tmp_path


def entrar(app, login, senha="1234"):
    cliente = app.test_client()
    r = cliente.post("/login", data={"usuario": login, "senha": senha})
    assert r.status_code == 302, r.data
    return cliente


@pytest.fixture
def admin(ambiente):
    app, banco, _ = ambiente
    banco.criar_primeiro_admin({"nome": "Ana", "login": "ana", "senha": "1234"})
    return entrar(app, "ana")


def criar_usuario(admin, login, permissoes):
    r = admin.post("/api/usuarios", json={"nome": login.capitalize(), "login": login, "senha": "1234", "permissoes": permissoes})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["usuario"]


def _imagem(formato="PNG", tamanho=(3000, 2000), modo="RGBA"):
    buf = io.BytesIO()
    Image.new(modo, tamanho, (200, 30, 30, 255) if modo == "RGBA" else (200, 30, 30)).save(buf, formato)
    buf.seek(0)
    return buf


def _produto(cliente, nome="X-Burger", preco=2500):
    r = cliente.post("/api/produtos", json={"nome": nome, "preco_centavos": preco, "categoria": "Lanches"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["produto"]


# --- Primeiro acesso, login e permissões -------------------------------------

def test_primeiro_acesso_cria_admin(ambiente):
    app, banco, _ = ambiente
    c = app.test_client()
    assert c.get("/caixa").headers["Location"].endswith("/primeiro-acesso")
    assert c.get("/login").headers["Location"].endswith("/primeiro-acesso")
    assert c.get("/api/estado").status_code == 401
    r = c.post("/primeiro-acesso", data={"nome": "Ana", "usuario": "ana", "senha": "1234", "confirmar": "9999"})
    assert r.status_code == 400 and "não conferem".encode() in r.data
    r = c.post("/primeiro-acesso", data={"nome": "Ana", "usuario": "ana", "senha": "1234", "confirmar": "1234"})
    assert r.status_code == 302 and c.get("/admin").status_code == 200
    # depois de criado, ninguém mais consegue usar o primeiro acesso
    outro = app.test_client()
    outro.post("/primeiro-acesso", data={"nome": "X", "usuario": "x", "senha": "1234", "confirmar": "1234"})
    assert len(banco.listar_usuarios()) == 1


def test_login_logout_e_redirecionamento(ambiente, admin):
    app, banco, _ = ambiente
    c = app.test_client()
    assert "/login?proximo=/caixa" in c.get("/caixa").headers["Location"]
    assert c.post("/login", data={"usuario": "ana", "senha": "errada"}).status_code == 401
    r = c.post("/login?proximo=/caixa", data={"usuario": "ana", "senha": "1234"})
    assert r.headers["Location"].endswith("/caixa")
    r = c.post("/login?proximo=//site-malicioso.com", data={"usuario": "ana", "senha": "1234"})
    assert r.headers["Location"] == "/"
    c.get("/sair")
    assert c.get("/api/estado").status_code == 401
    acoes = [a["acao"] for a in banco.listar_auditoria("2000-01-01", "2100-01-01")]
    assert "Saiu do sistema" in acoes and "Tentativa de login recusada" in acoes


@pytest.mark.parametrize("caminho", ["/", "/caixa", "/cozinha", "/garcom", "/painel", "/admin", "/admin/qrcodes"])
def test_telas_abrem_para_o_admin(admin, caminho):
    r = admin.get(caminho)
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"


def test_painel_e_qrcode_continuam_publicos(ambiente, admin):
    app, banco, _ = ambiente
    mesa = banco.criar_mesa("3")
    anonimo = app.test_client()
    assert anonimo.get("/painel").status_code == 200
    assert anonimo.get("/api/painel").status_code == 200
    assert anonimo.get(f"/m/{mesa['token']}").status_code == 200
    assert anonimo.get(f"/api/cliente/{mesa['token']}").status_code == 200


def test_cada_usuario_so_acessa_o_que_o_admin_liberou(ambiente, admin):
    app, _, _ = ambiente
    criar_usuario(admin, "cozinheiro", ["cozinha"])
    criar_usuario(admin, "garcom", ["pedidos"])
    cozinha = entrar(app, "cozinheiro")
    garcom = entrar(app, "garcom")

    assert cozinha.get("/cozinha").status_code == 200
    assert cozinha.get("/caixa").status_code == 403
    assert cozinha.get("/admin").status_code == 403
    assert cozinha.post("/api/pedidos", json={"itens": []}).status_code == 403
    assert cozinha.get("/api/estado").status_code == 200

    assert garcom.get("/caixa").status_code == 200
    assert garcom.get("/cozinha").status_code == 403
    assert garcom.get("/api/produtos").status_code == 403          # cadastro = permissão "cardapio"
    assert garcom.post("/api/caixa/abrir", json={}).status_code == 403
    assert garcom.post("/api/recebimentos", json={}).status_code == 403
    assert garcom.get("/api/relatorios").status_code == 403
    assert garcom.get("/api/auditoria").status_code == 403
    assert garcom.get("/api/usuarios").status_code == 403

    # a página inicial só mostra os atalhos permitidos
    inicio = garcom.get("/").data.decode()
    assert 'href="/caixa"' in inicio and 'href="/cozinha"' not in inicio and 'href="/admin"' not in inicio


def test_permissoes_por_acao_no_pedido(ambiente, admin):
    app, _, _ = ambiente
    p = _produto(admin)
    pedido = admin.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}]}).get_json()["pedido"]
    criar_usuario(admin, "cozinheiro", ["cozinha"])
    criar_usuario(admin, "garcom", ["pedidos"])
    cozinha, garcom = entrar(app, "cozinheiro"), entrar(app, "garcom")

    assert cozinha.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "pronto"}).status_code == 200
    assert cozinha.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "entregue"}).status_code == 403
    assert cozinha.post(f"/api/pedidos/{pedido['id']}/chamar").status_code == 403
    assert garcom.post(f"/api/pedidos/{pedido['id']}/chamar").status_code == 200
    r = garcom.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "cancelado", "motivo": "x"})
    assert r.status_code == 403  # cancelar é permissão separada


def test_permissao_retirada_vale_na_hora(ambiente, admin):
    app, _, _ = ambiente
    beto = criar_usuario(admin, "beto", ["pedidos"])
    c = entrar(app, "beto")
    assert c.get("/caixa").status_code == 200
    admin.put(f"/api/usuarios/{beto['id']}", json={"permissoes": ["cozinha"]})
    assert c.get("/caixa").status_code == 403
    admin.put(f"/api/usuarios/{beto['id']}", json={"ativo": False})
    assert c.get("/api/estado").status_code == 401


def test_admin_nao_pode_se_trancar_para_fora(ambiente, admin):
    app, banco, _ = ambiente
    ana = banco.listar_usuarios()[0]
    r = admin.put(f"/api/usuarios/{ana['id']}", json={"permissoes": ["pedidos"]})
    assert r.status_code == 400 and "pelo menos um" in r.get_json()["erro"]


def test_trocar_propria_senha(ambiente, admin):
    app, _, _ = ambiente
    assert admin.post("/api/minha-senha", json={"atual": "errada", "nova": "5555"}).status_code == 400
    assert admin.post("/api/minha-senha", json={"atual": "1234", "nova": "5555"}).status_code == 200
    entrar(app, "ana", "5555")


# --- Fluxo de pedido e caixa --------------------------------------------------

def test_fluxo_completo_pedido_caixa_cozinha_painel_e_pagamento(ambiente, admin):
    app, banco, _ = ambiente
    criar_usuario(admin, "caixa", ["pedidos", "receber", "caixa"])
    caixa = entrar(app, "caixa")
    p = _produto(admin)
    r = caixa.post("/api/pedidos", json={"itens": [{"produto_id": p["id"], "quantidade": 2}], "cliente": "Maria"})
    pedido = r.get_json()["pedido"]
    assert pedido["total_centavos"] == 5000 and pedido["usuario_nome"] == "Caixa"

    estado = caixa.get("/api/estado").get_json()
    assert [x["codigo"] for x in estado["pedidos"]] == ["1"]
    assert estado["contas"][0]["total"] == 5000 and estado["caixa_aberto"] is False
    versao = estado["versao"]
    assert caixa.get(f"/api/estado?v={versao}").get_json() == {"versao": versao, "mudou": False}

    caixa.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "pronto"})
    caixa.post(f"/api/pedidos/{pedido['id']}/chamar")
    assert app.test_client().get("/api/painel").get_json()["chamadas"][0]["cliente"] == "Maria"

    assert caixa.post("/api/recebimentos", json={"pedido_ids": [pedido["id"]], "formas": [{"forma": "pix", "valor": 5000}]}).status_code == 400
    assert caixa.post("/api/caixa/abrir", json={"valor_abertura": 10000}).status_code == 200
    r = caixa.post("/api/recebimentos", json={"pedido_ids": [pedido["id"]], "formas": [{"forma": "dinheiro", "valor": 10000}]})
    assert r.get_json()["recebimento"]["troco"] == 5000

    estado = caixa.get("/api/estado").get_json()
    assert estado["contas"] == [] and estado["sessao"]["total_vendas"] == 5000
    assert "esperado_dinheiro" not in estado["sessao"]  # fechamento cego
    assert len(estado["recebimentos"]) == 1

    r = caixa.post("/api/caixa/fechar", json={"valor_contado": 15000})
    s = r.get_json()["sessao"]
    assert s["esperado_dinheiro"] == 15000 and s["diferenca"] == 0

    acoes = [a["acao"] for a in banco.listar_auditoria("2000-01-01", "2100-01-01") if a["usuario_nome"] == "Caixa"]
    for esperada in ("Lançou pedido", "Marcou pronto", "Chamou no painel", "Abriu o caixa", "Recebeu pagamento", "Fechou o caixa"):
        assert esperada in acoes


def test_estorno_e_cancelamento_exigem_permissao_cancelar(ambiente, admin):
    app, _, _ = ambiente
    p = _produto(admin, preco=1000)
    pedido = admin.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}]}).get_json()["pedido"]
    admin.post("/api/caixa/abrir", json={"valor_abertura": 0})
    rec = admin.post("/api/recebimentos", json={"pedido_ids": [pedido["id"]], "formas": [{"forma": "pix", "valor": 1000}]}).get_json()["recebimento"]
    criar_usuario(admin, "caixa", ["pedidos", "receber"])
    caixa = entrar(app, "caixa")
    assert caixa.post(f"/api/recebimentos/{rec['id']}/estornar", json={"motivo": "x"}).status_code == 403
    assert admin.post(f"/api/recebimentos/{rec['id']}/estornar", json={"motivo": "lançado errado"}).status_code == 200
    r = admin.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "cancelado"})
    assert r.status_code == 400 and "motivo" in r.get_json()["erro"]
    assert admin.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "cancelado", "motivo": "desistiu"}).status_code == 200


def test_sangria_e_suprimento(admin):
    admin.post("/api/caixa/abrir", json={"valor_abertura": 5000})
    assert admin.post("/api/caixa/movimento", json={"tipo": "suprimento", "valor": 2000, "motivo": "troco"}).status_code == 200
    r = admin.post("/api/caixa/movimento", json={"tipo": "sangria", "valor": 999999, "motivo": "x"})
    assert r.status_code == 400 and "Sangria maior" in r.get_json()["erro"]
    assert admin.post("/api/caixa/movimento", json={"tipo": "sangria", "valor": 3000, "motivo": "banco"}).status_code == 200
    s = admin.post("/api/caixa/fechar", json={"valor_contado": 4000}).get_json()["sessao"]
    assert s["esperado_dinheiro"] == 4000 and s["sangrias"] == 3000 and s["suprimentos"] == 2000


def test_relatorio_csv_e_historico(ambiente, admin):
    p = _produto(admin, "Pão de queijo", 500)
    pedido = admin.post("/api/pedidos", json={"itens": [{"produto_id": p["id"], "quantidade": 3}]}).get_json()["pedido"]
    admin.post("/api/caixa/abrir", json={"valor_abertura": 0})
    admin.post("/api/recebimentos", json={"pedido_ids": [pedido["id"]], "formas": [{"forma": "debito", "valor": 1500}]})
    r = admin.get("/api/relatorios").get_json()
    assert r["relatorio"]["total_vendas"] == 1500 and r["relatorio"]["por_forma"]["debito"] == 1500
    assert r["relatorio"]["por_produto"] == [{"nome": "Pão de queijo", "quantidade": 3, "valor": 1500}]
    csv = admin.get("/api/relatorios/vendas.csv")
    assert csv.mimetype == "text/csv" and "attachment" in csv.headers["Content-Disposition"]
    assert "15,00" in csv.data.decode("utf-8-sig")
    hist = admin.get("/api/auditoria?busca=pão").get_json()
    assert hist["registros"] and hist["usuarios"][0]["nome"] == "Ana"
    assert admin.get("/api/relatorios?de=2026-13-01&ate=2026-01-01").status_code == 400


def test_erros_de_negocio_viram_400_com_mensagem(admin):
    r = admin.post("/api/pedidos", json={"itens": []})
    assert r.status_code == 400 and r.get_json() == {"ok": False, "erro": "O pedido está vazio."}


# --- Cliente (QR code) ----------------------------------------------------------

def test_cliente_qrcode_pede_e_chama_garcom(ambiente, admin):
    app, banco, _ = ambiente
    p = _produto(admin)
    mesa = banco.criar_mesa("7")
    c = app.test_client()
    r = c.post(f"/api/cliente/{mesa['token']}/pedido", json={"itens": [{"produto_id": p["id"]}], "cliente": "Léo"})
    assert r.status_code == 200
    pedido = banco.listar_pedidos()[0]
    assert pedido["origem"] == "qrcode" and pedido["mesa"] == "7" and pedido["usuario_nome"] == "Cliente (mesa 7)"
    c.post(f"/api/cliente/{mesa['token']}/chamar", json={"tipo": "conta"})
    dados = c.get(f"/api/cliente/{mesa['token']}").get_json()
    assert dados["chamados"] == ["conta"] and "impressao" not in dados["pedidos"][0]
    assert admin.get("/api/estado").get_json()["contas"][0]["titulo"] == "Mesa 7"


def test_cliente_token_invalido_e_pedidos_desativados(ambiente, admin):
    app, banco, _ = ambiente
    c = app.test_client()
    assert c.get("/m/nao-existe").status_code == 404
    assert c.get("/api/cliente/nao-existe").status_code == 404
    p = _produto(admin)
    mesa = banco.criar_mesa("1")
    banco.salvar_config({"pedidos_qrcode_ativo": False})
    r = c.post(f"/api/cliente/{mesa['token']}/pedido", json={"itens": [{"produto_id": p["id"]}]})
    assert r.status_code == 400 and "desativados" in r.get_json()["erro"]
    assert c.post(f"/api/cliente/{mesa['token']}/chamar", json={}).status_code == 200


# --- Cadastro, mídias, QR ------------------------------------------------------

def test_foto_de_produto_e_redimensionada_para_jpeg(ambiente, admin):
    _, _, pasta = ambiente
    p = _produto(admin)
    r = admin.post(f"/api/produtos/{p['id']}/foto", data={"arquivo": (_imagem(), "lanche.png")}, content_type="multipart/form-data")
    produto = r.get_json()["produto"]
    arquivo = pasta / "fotos" / produto["foto"]
    with Image.open(arquivo) as img:
        assert img.format == "JPEG" and max(img.size) == 900 and img.mode == "RGB"
    admin.post(f"/api/produtos/{p['id']}/foto", data={"arquivo": (_imagem("JPEG", (400, 300), "RGB"), "b.jpg")},
               content_type="multipart/form-data")
    assert not arquivo.exists()
    r = admin.post(f"/api/produtos/{p['id']}/foto", data={"arquivo": (io.BytesIO(b"nada"), "x.jpg")}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_upload_midias_do_painel(ambiente, admin):
    app, _, pasta = ambiente
    r = admin.post("/api/midias", data={"arquivos": [
        (_imagem(), "promo.png"), (io.BytesIO(b"\x00\x00\x00\x18ftypmp42fake"), "video.mp4"), (io.BytesIO(b"texto"), "leia.txt"),
    ]}, content_type="multipart/form-data")
    assert r.get_json()["adicionadas"] == 2 and r.get_json()["recusados"] == ["leia.txt"]
    painel = app.test_client().get("/api/painel").get_json()
    assert [m["tipo"] for m in painel["midias"]] == ["foto", "video"]
    r = app.test_client().get(painel["midias"][1]["url"], headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and r.data == b"\x00\x00\x00\x18"


def test_qrcode_da_mesa_usa_endereco_da_rede(ambiente, admin):
    _, banco, _ = ambiente
    mesa = banco.criar_mesa("4")
    r = admin.get(f"/qrcode/mesa/{mesa['id']}.svg")
    assert r.status_code == 200 and b"<svg" in r.data
    assert admin.get("/api/mesas").get_json()["mesas"][0]["link"] == f"http://192.168.0.10:8090/m/{mesa['token']}"
    banco.salvar_config({"url_base": "http://10.0.0.5:9000/"})
    assert admin.get("/api/mesas").get_json()["mesas"][0]["link"] == f"http://10.0.0.5:9000/m/{mesa['token']}"


def test_config_nao_aceita_segredo(ambiente, admin):
    _, banco, _ = ambiente
    chave = banco.secret_key()
    admin.put("/api/config", json={"secret_key": "hack", "nome_loja": "Lanchonete"})
    assert banco.secret_key() == chave and banco.config()["nome_loja"] == "Lanchonete"


# --- Impressão -----------------------------------------------------------------

def test_impressao_na_cozinha_por_tcp(ambiente, admin, impressora_falsa):
    _, banco, _ = ambiente
    banco.salvar_config({"impressora_cozinha_ativa": True, "impressora_cozinha_host": "127.0.0.1",
                         "impressora_cozinha_porta": impressora_falsa.porta})
    p = _produto(admin, "Pão de queijo")
    r = admin.post("/api/pedidos", json={"itens": [{"produto_id": p["id"], "quantidade": 3}]})
    assert r.get_json()["pedido"]["impressao"] == "ok"
    assert "Pão de queijo".encode("cp850") in impressora_falsa.esperar()[0]
    admin.post(f"/api/pedidos/{r.get_json()['pedido']['id']}/imprimir")
    assert len(impressora_falsa.esperar(2)) == 2


def test_falha_de_impressao_nao_impede_o_pedido(ambiente, admin):
    _, banco, _ = ambiente
    banco.salvar_config({"impressora_cozinha_ativa": True, "impressora_cozinha_host": "127.0.0.1", "impressora_cozinha_porta": 1})
    p = _produto(admin)
    r = admin.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}]})
    assert r.status_code == 200 and r.get_json()["pedido"]["impressao"].startswith("erro")


def test_impressora_do_caixa_conta_e_fechamento(ambiente, admin, impressora_falsa):
    _, banco, _ = ambiente
    banco.salvar_config({"impressora_caixa_ativa": True, "impressora_caixa_host": "127.0.0.1",
                         "impressora_caixa_porta": impressora_falsa.porta})
    p = _produto(admin, preco=2000)
    pedido = admin.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}], "mesa": "5"}).get_json()["pedido"]
    assert admin.post("/api/contas/imprimir", json={"pedido_ids": [pedido["id"]], "titulo": "Mesa 5"}).status_code == 200
    assert b"Mesa 5" in impressora_falsa.esperar()[0]
    admin.post("/api/caixa/abrir", json={"valor_abertura": 0})
    r = admin.post("/api/caixa/fechar", json={"valor_contado": 0})
    assert r.get_json()["impresso"] is True
    assert b"FECHAMENTO DE CAIXA" in impressora_falsa.esperar(2)[1]


def test_teste_de_impressora(ambiente, admin, impressora_falsa):
    _, banco, _ = ambiente
    banco.salvar_config({"impressora_caixa_host": "127.0.0.1", "impressora_caixa_porta": impressora_falsa.porta})
    assert admin.post("/api/impressora/teste", json={"qual": "caixa"}).status_code == 200
    assert b"TESTE OK" in impressora_falsa.esperar()[0]
    assert admin.post("/api/impressora/teste", json={"qual": "outra"}).status_code == 400
    assert admin.post("/api/impressora/teste", json={"qual": "cozinha"}).status_code == 400  # sem IP


def test_arquivos_nao_escapam_da_pasta(ambiente):
    app, _, pasta = ambiente
    (pasta / "segredo.txt").write_text("x")
    c = app.test_client()
    assert c.get("/foto/..%2Fsegredo.txt").status_code == 404
    assert c.get("/midia/../segredo.txt").status_code == 404


# --- Garçom, itens fora da cozinha e estorno ------------------------------------

def test_pagina_do_garcom_e_pedido_na_mesa(ambiente, admin):
    app, banco, _ = ambiente
    p = _produto(admin)
    banco.criar_mesa("8")
    criar_usuario(admin, "carlos", ["garcom"])
    garcom = entrar(app, "carlos")
    assert garcom.get("/garcom").status_code == 200
    assert garcom.get("/caixa").status_code == 403
    estado = garcom.get("/api/estado").get_json()
    assert estado["mesas"] == ["8"] and estado["produtos"][0]["nome"] == "X-Burger"
    r = garcom.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}]})
    assert r.status_code == 400 and "mesa" in r.get_json()["erro"]
    r = garcom.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}], "mesa": "8"})
    pedido = r.get_json()["pedido"]
    assert pedido["origem"] == "garcom" and pedido["usuario_nome"] == "Carlos"
    # não recebe, não cancela, não chama no painel
    assert garcom.post("/api/caixa/abrir", json={}).status_code == 403
    assert garcom.post(f"/api/pedidos/{pedido['id']}/chamar").status_code == 403
    assert garcom.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "cancelado", "motivo": "x"}).status_code == 403
    # entrega na mesa
    admin.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "pronto"})
    assert garcom.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "entregue"}).status_code == 200
    assert garcom.get("/api/estado").get_json()["contas"][0]["titulo"] == "Mesa 8"


def test_garcom_recebe_chamado_do_qrcode(ambiente, admin):
    app, banco, _ = ambiente
    mesa = banco.criar_mesa("5")
    criar_usuario(admin, "carlos", ["garcom"])
    garcom = entrar(app, "carlos")
    app.test_client().post(f"/api/cliente/{mesa['token']}/chamar", json={"tipo": "garcom"})
    chamados = garcom.get("/api/estado").get_json()["chamados_garcom"]
    assert [(c["mesa"], c["tipo"]) for c in chamados] == [("5", "garcom")]
    assert garcom.post(f"/api/garcom/{chamados[0]['id']}/atender").status_code == 200
    assert garcom.get("/api/estado").get_json()["chamados_garcom"] == []
    assert "Atendeu chamado" in [a["acao"] for a in banco.listar_auditoria("2000-01-01", "2100-01-01") if a["usuario_nome"] == "Carlos"]


def test_itens_sem_preparo_nao_vao_para_a_impressora_da_cozinha(ambiente, admin, impressora_falsa):
    _, banco, _ = ambiente
    banco.salvar_config({"impressora_cozinha_ativa": True, "impressora_cozinha_host": "127.0.0.1",
                         "impressora_cozinha_porta": impressora_falsa.porta})
    lata = admin.post("/api/produtos", json={"nome": "Coca lata", "preco_centavos": 600, "vai_cozinha": False}).get_json()["produto"]
    burger = _produto(admin)
    so_lata = admin.post("/api/pedidos", json={"itens": [{"produto_id": lata["id"]}]}).get_json()["pedido"]
    assert so_lata["status"] == "pronto" and so_lata["impressao"] == ""
    r = admin.post(f"/api/pedidos/{so_lata['id']}/imprimir")
    assert r.status_code == 400 and "nada para a cozinha" in r.get_json()["erro"]
    misto = admin.post("/api/pedidos", json={"itens": [{"produto_id": lata["id"]}, {"produto_id": burger["id"]}]}).get_json()["pedido"]
    assert misto["status"] == "novo" and misto["impressao"] == "ok"
    cupom = impressora_falsa.esperar()[0]
    assert b"X-Burger" in cupom and b"Coca lata" not in cupom
    assert len(impressora_falsa.recebidos) == 1


def test_categoria_cozinha_pela_api(admin):
    admin.post("/api/produtos", json={"nome": "Coca", "preco_centavos": 600, "categoria": "Bebidas"})
    r = admin.post("/api/produtos/categoria-cozinha", json={"categoria": "Bebidas", "vai_cozinha": False})
    assert r.get_json()["alterados"] == 1
    assert admin.get("/api/produtos").get_json()["produtos"][0]["vai_cozinha"] is False


def test_estorno_so_com_permissao_propria(ambiente, admin):
    app, _, _ = ambiente
    p = _produto(admin, preco=1000)
    pedido = admin.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}]}).get_json()["pedido"]
    admin.post("/api/caixa/abrir", json={"valor_abertura": 0})
    rec = admin.post("/api/recebimentos", json={"pedido_ids": [pedido["id"]], "formas": [{"forma": "pix", "valor": 1000}]}).get_json()["recebimento"]
    criar_usuario(admin, "gerente", ["pedidos", "receber", "cancelar"])
    criar_usuario(admin, "chefe", ["pedidos", "receber", "estornar"])
    gerente, chefe = entrar(app, "gerente"), entrar(app, "chefe")
    # cancelar pedido NÃO dá direito a estornar pagamento
    assert gerente.post(f"/api/recebimentos/{rec['id']}/estornar", json={"motivo": "x"}).status_code == 403
    pagina = gerente.get("/caixa").data.decode()
    assert 'data-pode-estornar="0"' in pagina
    assert chefe.post(f"/api/recebimentos/{rec['id']}/estornar", json={"motivo": "lançado errado"}).status_code == 200


def test_modelo_caixa_nao_inclui_estorno(admin):
    modelos = admin.get("/api/usuarios").get_json()["modelos"]
    assert "estornar" not in modelos["caixa"]["permissoes"]
    assert modelos["garcom"]["permissoes"] == ["garcom"]
    assert "estornar" in modelos["admin"]["permissoes"]
