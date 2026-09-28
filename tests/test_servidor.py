import io

import pytest
from PIL import Image

from comandas.banco import Banco
from comandas.servidor import criar_app


@pytest.fixture
def ambiente(tmp_path):
    banco = Banco(tmp_path / "t.db")
    app = criar_app(banco, tmp_path, url_base_padrao="http://192.168.0.10:8090", impressao_sincrona=True)
    return app.test_client(), banco, tmp_path


def _imagem(formato="PNG", tamanho=(3000, 2000), modo="RGBA"):
    buf = io.BytesIO()
    Image.new(modo, tamanho, (200, 30, 30, 255) if modo == "RGBA" else (200, 30, 30)).save(buf, formato)
    buf.seek(0)
    return buf


def _produto(cliente, nome="X-Burger", preco=2500, categoria="Lanches"):
    r = cliente.post("/api/produtos", json={"nome": nome, "preco_centavos": preco, "categoria": categoria})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["produto"]


@pytest.mark.parametrize("caminho", ["/", "/caixa", "/cozinha", "/painel", "/totem", "/admin", "/login"])
def test_telas_abrem(ambiente, caminho):
    cliente, _, _ = ambiente
    r = cliente.get(caminho)
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"


def test_fluxo_completo_caixa_cozinha_painel(ambiente):
    cliente, _, _ = ambiente
    p = _produto(cliente)
    r = cliente.post("/api/pedidos", json={"itens": [{"produto_id": p["id"], "quantidade": 2}], "cliente": "Maria"})
    pedido = r.get_json()["pedido"]
    assert pedido["total_centavos"] == 5000

    estado = cliente.get("/api/estado").get_json()
    assert [x["codigo"] for x in estado["pedidos"]] == ["1"]
    versao = estado["versao"]
    # sem mudança: resposta curta
    assert cliente.get(f"/api/estado?v={versao}").get_json() == {"versao": versao, "mudou": False}

    cliente.post(f"/api/pedidos/{pedido['id']}/status", json={"status": "pronto"})
    assert cliente.get("/api/painel").get_json()["chamadas"] == []
    cliente.post(f"/api/pedidos/{pedido['id']}/chamar", json={})
    painel = cliente.get("/api/painel").get_json()
    assert painel["chamadas"][0]["codigo"] == "1"
    assert painel["chamadas"][0]["cliente"] == "Maria"


def test_painel_pode_esconder_nome_do_cliente(ambiente):
    cliente, banco, _ = ambiente
    banco.salvar_config({"mostrar_nome_cliente_painel": False})
    p = _produto(cliente)
    pedido = cliente.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}], "cliente": "Maria"}).get_json()["pedido"]
    cliente.post(f"/api/pedidos/{pedido['id']}/chamar", json={})
    assert cliente.get("/api/painel").get_json()["chamadas"][0]["cliente"] == ""


def test_erros_de_negocio_viram_400_com_mensagem(ambiente):
    cliente, _, _ = ambiente
    r = cliente.post("/api/pedidos", json={"itens": []})
    assert r.status_code == 400
    assert r.get_json() == {"ok": False, "erro": "O pedido está vazio."}
    r = cliente.post("/api/pedidos/999/status", json={"status": "pronto"})
    assert r.status_code == 400


def test_cliente_qrcode_pede_e_chama_garcom(ambiente):
    cliente, banco, _ = ambiente
    p = _produto(cliente)
    mesa = banco.criar_mesa("7")
    tela = cliente.get(f"/m/{mesa['token']}")
    assert tela.status_code == 200

    dados = cliente.get(f"/api/cliente/{mesa['token']}").get_json()
    assert dados["mesa"] == "7" and dados["produtos"][0]["nome"] == "X-Burger"

    r = cliente.post(f"/api/cliente/{mesa['token']}/pedido",
                     json={"itens": [{"produto_id": p["id"], "quantidade": 1}], "cliente": "Léo"})
    assert r.status_code == 200
    pedido = banco.listar_pedidos()[0]
    assert pedido["origem"] == "qrcode" and pedido["mesa"] == "7"

    cliente.post(f"/api/cliente/{mesa['token']}/chamar", json={"tipo": "conta"})
    assert cliente.get(f"/api/cliente/{mesa['token']}").get_json()["chamados"] == ["conta"]
    assert banco.chamados_pendentes()[0]["mesa"] == "7"
    # o cliente vê o próprio pedido, mas sem dados internos (impressão etc.)
    meus = cliente.get(f"/api/cliente/{mesa['token']}").get_json()["pedidos"]
    assert meus[0]["codigo"] == "1" and "impressao" not in meus[0]


def test_cliente_token_invalido_e_pedidos_desativados(ambiente):
    cliente, banco, _ = ambiente
    assert cliente.get("/m/nao-existe").status_code == 404
    assert cliente.get("/api/cliente/nao-existe").status_code == 404
    assert cliente.post("/api/cliente/nao-existe/chamar", json={}).status_code == 404

    p = _produto(cliente)
    mesa = banco.criar_mesa("1")
    banco.salvar_config({"pedidos_qrcode_ativo": False})
    r = cliente.post(f"/api/cliente/{mesa['token']}/pedido", json={"itens": [{"produto_id": p["id"]}]})
    assert r.status_code == 400 and "desativados" in r.get_json()["erro"]
    # chamar garçom continua funcionando
    assert cliente.post(f"/api/cliente/{mesa['token']}/chamar", json={}).status_code == 200


def test_pin_protege_equipe_mas_nao_painel_nem_cliente(ambiente):
    cliente, banco, _ = ambiente
    mesa = banco.criar_mesa("3")
    r = cliente.put("/api/config", json={"novo_pin": "4321"})
    assert r.get_json()["config"]["pin_definido"] is True

    anonimo = cliente.application.test_client()
    assert anonimo.get("/caixa").status_code == 302
    assert "/login" in anonimo.get("/admin").headers["Location"]
    assert anonimo.get("/api/estado").status_code == 401
    assert anonimo.post("/api/pedidos", json={}).status_code == 401
    assert anonimo.get("/api/config").status_code == 401
    assert anonimo.get("/painel").status_code == 200
    assert anonimo.get("/api/painel").status_code == 200
    assert anonimo.get(f"/api/cliente/{mesa['token']}").status_code == 200

    assert anonimo.post("/login?proximo=/caixa", data={"pin": "0000"}).status_code == 401
    r = anonimo.post("/login?proximo=/caixa", data={"pin": "4321"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/caixa")
    assert anonimo.get("/api/estado").status_code == 200

    # redirecionamento externo não é aceito
    r = anonimo.post("/login?proximo=//site-malicioso.com", data={"pin": "4321"})
    assert r.headers["Location"] == "/"


def test_pin_invalido_e_remocao(ambiente):
    cliente, _, _ = ambiente
    assert cliente.put("/api/config", json={"novo_pin": "12"}).status_code == 400
    assert cliente.put("/api/config", json={"novo_pin": "abcd"}).status_code == 400
    cliente.put("/api/config", json={"novo_pin": "1234"})
    r = cliente.put("/api/config", json={"remover_pin": True})
    assert r.get_json()["config"]["pin_definido"] is False
    # não dá pra injetar hash/segredo direto pela API
    cliente.put("/api/config", json={"pin_hash": "x", "secret_key": "y"})
    assert cliente.application.test_client().get("/caixa").status_code == 200


def test_foto_de_produto_e_redimensionada_para_jpeg(ambiente):
    cliente, _, pasta = ambiente
    p = _produto(cliente)
    r = cliente.post(f"/api/produtos/{p['id']}/foto", data={"arquivo": (_imagem(), "lanche.png")},
                     content_type="multipart/form-data")
    produto = r.get_json()["produto"]
    arquivo = pasta / "fotos" / produto["foto"]
    with Image.open(arquivo) as img:
        assert img.format == "JPEG" and max(img.size) == 900 and img.mode == "RGB"
    assert cliente.get("/foto/" + produto["foto"]).status_code == 200

    # trocar a foto apaga a antiga
    r = cliente.post(f"/api/produtos/{p['id']}/foto", data={"arquivo": (_imagem("JPEG", (400, 300), "RGB"), "b.jpg")},
                     content_type="multipart/form-data")
    assert not arquivo.exists()
    # arquivo que não é imagem
    r = cliente.post(f"/api/produtos/{p['id']}/foto", data={"arquivo": (io.BytesIO(b"nada"), "x.jpg")},
                     content_type="multipart/form-data")
    assert r.status_code == 400


def test_upload_midias_do_painel(ambiente):
    cliente, _, pasta = ambiente
    r = cliente.post("/api/midias", data={"arquivos": [
        (_imagem(), "promo.png"),
        (io.BytesIO(b"\x00\x00\x00\x18ftypmp42fake"), "video.mp4"),
        (io.BytesIO(b"texto"), "leia.txt"),
    ]}, content_type="multipart/form-data")
    dados = r.get_json()
    assert dados["adicionadas"] == 2 and dados["recusados"] == ["leia.txt"]
    painel = cliente.get("/api/painel").get_json()
    assert [m["tipo"] for m in painel["midias"]] == ["foto", "video"]
    video_url = painel["midias"][1]["url"]
    # vídeo servido com suporte a Range (necessário pra TVs/celulares)
    r = cliente.get(video_url, headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and r.data == b"\x00\x00\x00\x18"

    midia_id = cliente.get("/api/midias").get_json()["midias"][0]["id"]
    arquivo = pasta / "midias" / cliente.get("/api/midias").get_json()["midias"][0]["arquivo"]
    cliente.delete(f"/api/midias/{midia_id}")
    assert not arquivo.exists()


def test_painel_sem_midia_usa_fotos_dos_produtos(ambiente):
    cliente, _, _ = ambiente
    p = _produto(cliente)
    _produto(cliente, "Sem foto")
    cliente.post(f"/api/produtos/{p['id']}/foto", data={"arquivo": (_imagem(), "a.png")}, content_type="multipart/form-data")
    painel = cliente.get("/api/painel").get_json()
    assert painel["midias"] == []
    assert [x["nome"] for x in painel["produtos"]] == ["X-Burger"]


def test_qrcode_da_mesa_contem_link_com_ip_da_rede(ambiente):
    cliente, banco, _ = ambiente
    mesa = banco.criar_mesa("4")
    r = cliente.get(f"/qrcode/mesa/{mesa['id']}.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and b"<svg" in r.data
    mesas = cliente.get("/api/mesas").get_json()["mesas"]
    assert mesas[0]["link"] == f"http://192.168.0.10:8090/m/{mesa['token']}"

    banco.salvar_config({"url_base": "http://10.0.0.5:9000/"})
    assert cliente.get("/api/mesas").get_json()["mesas"][0]["link"] == f"http://10.0.0.5:9000/m/{mesa['token']}"
    folha = cliente.get("/admin/qrcodes")
    assert folha.status_code == 200 and b"Mesa 4" in folha.data


def test_impressao_na_cozinha_por_tcp(ambiente, impressora_falsa):
    cliente, banco, _ = ambiente
    banco.salvar_config({"impressora_cozinha_ativa": True, "impressora_cozinha_host": "127.0.0.1",
                         "impressora_cozinha_porta": impressora_falsa.porta, "nome_loja": "Lanchonete Zé"})
    p = _produto(cliente, "Pão de queijo")
    r = cliente.post("/api/pedidos", json={"itens": [{"produto_id": p["id"], "quantidade": 3}]})
    assert r.get_json()["pedido"]["impressao"] == "ok"
    recebido = impressora_falsa.esperar()[0]
    assert "Pão de queijo".encode("cp850") in recebido and b"3x" in recebido

    # reimpressão
    cliente.post(f"/api/pedidos/{r.get_json()['pedido']['id']}/imprimir")
    assert len(impressora_falsa.esperar(2)) == 2


def test_falha_de_impressao_nao_impede_o_pedido(ambiente):
    cliente, banco, _ = ambiente
    banco.salvar_config({"impressora_cozinha_ativa": True, "impressora_cozinha_host": "127.0.0.1",
                         "impressora_cozinha_porta": 1})
    p = _produto(cliente)
    r = cliente.post("/api/pedidos", json={"itens": [{"produto_id": p["id"]}]})
    assert r.status_code == 200
    assert r.get_json()["pedido"]["impressao"].startswith("erro")
    assert len(banco.listar_pedidos()) == 1


def test_senha_do_totem_impressa(ambiente, impressora_falsa):
    cliente, banco, _ = ambiente
    banco.salvar_config({"impressora_senhas_ativa": True, "impressora_senhas_host": "127.0.0.1",
                         "impressora_senhas_porta": impressora_falsa.porta})
    r = cliente.post("/api/senhas", json={"prefixo": "P", "origem": "totem"}).get_json()
    assert r["senha"]["codigo"] == "P001" and r["senha"]["origem"] == "totem" and r["impressa"] is True
    assert b"P001" in impressora_falsa.esperar()[0]

    r = cliente.post("/api/senhas/chamar-proxima", json={"guiche": "3"}).get_json()
    assert r["senha"]["codigo"] == "P001"
    painel = cliente.get("/api/painel").get_json()["chamadas"][0]
    assert painel["tipo"] == "senha" and painel["guiche"] == "3"
    assert cliente.post("/api/senhas/chamar-proxima", json={"guiche": "3"}).get_json()["ok"] is False


def test_teste_de_impressora(ambiente, impressora_falsa):
    cliente, banco, _ = ambiente
    banco.salvar_config({"impressora_cozinha_host": "127.0.0.1", "impressora_cozinha_porta": impressora_falsa.porta})
    assert cliente.post("/api/impressora/teste", json={"qual": "cozinha"}).status_code == 200
    assert b"TESTE OK" in impressora_falsa.esperar()[0]
    assert cliente.post("/api/impressora/teste", json={"qual": "outra"}).status_code == 400
    assert cliente.post("/api/impressora/teste", json={"qual": "senhas"}).status_code == 400  # sem IP


def test_arquivos_nao_escapam_da_pasta(ambiente):
    cliente, _, pasta = ambiente
    (pasta / "segredo.txt").write_text("x")
    assert cliente.get("/foto/..%2Fsegredo.txt").status_code == 404
    assert cliente.get("/midia/../segredo.txt").status_code == 404
