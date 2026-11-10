import sqlite3

import pytest

from comandas.banco import PERMISSOES, Banco, ErroNegocio


class Relogio:
    def __init__(self, ts=1_790_000_000.0):
        self.ts = ts

    def __call__(self):
        return self.ts


@pytest.fixture
def relogio():
    return Relogio()


@pytest.fixture
def banco(tmp_path, relogio):
    return Banco(tmp_path / "t.db", agora=relogio)


@pytest.fixture
def ana(banco):
    u = banco.criar_primeiro_admin({"nome": "Ana", "login": "ana", "senha": "1234"})
    return {"id": u["id"], "nome": u["nome"]}


def _produto(banco, nome="X-Burger", preco=2500, **extra):
    return banco.criar_produto({"nome": nome, "preco_centavos": preco, "categoria": "Lanches", **extra})


def _pedido(banco, produto, qtd=1, **extra):
    return banco.criar_pedido([{"produto_id": produto["id"], "quantidade": qtd}], **extra)


def _acoes(banco):
    return [a["acao"] for a in banco.listar_auditoria("2000-01-01", "2100-01-01")][::-1]


# --- Pedidos ------------------------------------------------------------------

def test_pedido_calcula_total_e_guarda_copia_dos_itens(banco):
    burger = _produto(banco)
    suco = _produto(banco, "Suco", 800)
    pedido = banco.criar_pedido([
        {"produto_id": burger["id"], "quantidade": 2, "observacao": "sem cebola"},
        {"produto_id": suco["id"], "quantidade": 1},
    ], cliente="Ana")
    assert pedido["codigo"] == "1" and pedido["status"] == "novo" and pedido["pago"] is False
    assert pedido["total_centavos"] == 2 * 2500 + 800
    banco.atualizar_produto(burger["id"], {"preco_centavos": 9999})
    assert banco.obter_pedido(pedido["id"])["total_centavos"] == 5800


def test_numeracao_reinicia_a_cada_dia(banco, relogio):
    p = _produto(banco)
    assert _pedido(banco, p)["codigo"] == "1"
    assert _pedido(banco, p)["codigo"] == "2"
    relogio.ts += 86400
    assert _pedido(banco, p)["codigo"] == "1"


def test_pedido_rejeita_vazio_produto_inativo_e_quantidade_invalida(banco):
    p = _produto(banco, ativo=False)
    ativo = _produto(banco, "Outro")
    for itens in ([], [{"produto_id": p["id"]}], [{"produto_id": ativo["id"], "quantidade": 0}], [{"produto_id": "abc"}]):
        with pytest.raises(ErroNegocio):
            banco.criar_pedido(itens)


def test_fluxo_cozinha_pronto_chamar_entregar(banco):
    p = _produto(banco)
    pedido = _pedido(banco, p, cliente="João")
    banco.mudar_status(pedido["id"], "preparando")
    assert banco.mudar_status(pedido["id"], "pronto")["pronto_em"]
    assert banco.chamadas_recentes() == []
    assert banco.chamar(pedido["id"])["status"] == "chamado"
    assert banco.chamadas_recentes()[0]["cliente"] == "João"
    banco.mudar_status(pedido["id"], "entregue")
    assert banco.listar_pedidos() == []
    with pytest.raises(ErroNegocio):
        banco.mudar_status(pedido["id"], "preparando")


def test_chamar_de_novo_sobe_para_o_topo_do_painel(banco):
    p = _produto(banco)
    a, b = _pedido(banco, p), _pedido(banco, p)
    banco.chamar(a["id"])
    banco.chamar(b["id"])
    banco.chamar(a["id"])
    assert [c["codigo"] for c in banco.chamadas_recentes()] == ["1", "2"]


def test_chamar_ao_ficar_pronto_automatico(banco):
    banco.salvar_config({"chamar_ao_ficar_pronto": True})
    pedido = _pedido(banco, _produto(banco))
    assert banco.mudar_status(pedido["id"], "pronto")["status"] == "chamado"


def test_cancelar_exige_motivo_e_registra_quem(banco, ana):
    pedido = _pedido(banco, _produto(banco))
    with pytest.raises(ErroNegocio, match="motivo"):
        banco.mudar_status(pedido["id"], "cancelado", por=ana)
    cancelado = banco.mudar_status(pedido["id"], "cancelado", por=ana, motivo="cliente desistiu")
    assert cancelado["cancelado_por_nome"] == "Ana" and cancelado["motivo_cancelamento"] == "cliente desistiu"
    with pytest.raises(ErroNegocio):
        banco.chamar(pedido["id"])


def test_chamado_garcom_nao_duplica_e_e_atendido(banco, ana):
    c1 = banco.chamar_garcom("5")
    assert banco.chamar_garcom("5")["id"] == c1["id"]
    banco.chamar_garcom("5", "conta")
    banco.atender_chamado(c1["id"], por=ana)
    assert [c["tipo"] for c in banco.chamados_pendentes("5")] == ["conta"]
    with pytest.raises(ErroNegocio):
        banco.chamar_garcom("5", "outro")


def test_mesas_tokens_unicos_lote_e_novo_token(banco):
    assert banco.criar_mesas_em_lote(1, 12) == 12
    mesas = banco.listar_mesas()
    assert len({m["token"] for m in mesas}) == 12
    assert [m["numero"] for m in mesas][:3] == ["1", "2", "3"]
    assert banco.criar_mesas_em_lote(10, 13) == 1
    with pytest.raises(ErroNegocio):
        banco.criar_mesa("1")
    nova = banco.novo_token_mesa(mesas[0]["id"])
    assert nova["token"] != mesas[0]["token"] and banco.mesa_por_token(mesas[0]["token"]) is None


# --- Usuários e permissões ----------------------------------------------------

def test_primeiro_admin_tem_todas_as_permissoes_e_so_pode_ser_criado_uma_vez(banco):
    assert not banco.existe_usuario()
    admin = banco.criar_primeiro_admin({"nome": "Ana", "login": "Ana", "senha": "1234"})
    assert admin["login"] == "ana"
    assert set(admin["permissoes"]) == set(PERMISSOES)
    with pytest.raises(ErroNegocio):
        banco.criar_primeiro_admin({"nome": "Outro", "login": "x", "senha": "1234"})


def test_autenticacao_e_senha_nao_vaza(banco, ana):
    u = banco.autenticar("ANA", "1234")
    assert u and "senha_hash" not in u
    assert banco.autenticar("ana", "errada") is None
    assert banco.autenticar("ninguem", "1234") is None
    acoes = _acoes(banco)
    assert "Entrou no sistema" in acoes and acoes.count("Tentativa de login recusada") == 2


def test_criar_usuario_validacoes(banco, ana):
    with pytest.raises(ErroNegocio, match="4 caracteres"):
        banco.criar_usuario({"nome": "Beto", "login": "beto", "senha": "12"}, por=ana)
    with pytest.raises(ErroNegocio, match="espaços"):
        banco.criar_usuario({"nome": "Beto", "login": "be to", "senha": "1234"}, por=ana)
    beto = banco.criar_usuario({"nome": "Beto", "login": "beto", "senha": "1234",
                                "permissoes": ["pedidos", "inexistente", "receber"]}, por=ana)
    assert beto["permissoes"] == ["pedidos", "receber"]
    with pytest.raises(ErroNegocio, match="Já existe"):
        banco.criar_usuario({"nome": "B2", "login": "BETO", "senha": "1234"}, por=ana)


def test_usuario_desativado_nao_entra(banco, ana):
    beto = banco.criar_usuario({"nome": "Beto", "login": "beto", "senha": "1234", "permissoes": ["pedidos"]}, por=ana)
    banco.atualizar_usuario(beto["id"], {"ativo": False}, por=ana)
    assert banco.autenticar("beto", "1234") is None
    banco.atualizar_usuario(beto["id"], {"ativo": True, "senha": "nova123"}, por=ana)
    assert banco.autenticar("beto", "nova123")


def test_nao_deixa_ficar_sem_administrador(banco, ana):
    with pytest.raises(ErroNegocio, match="pelo menos um"):
        banco.atualizar_usuario(ana["id"], {"ativo": False}, por=ana)
    with pytest.raises(ErroNegocio, match="pelo menos um"):
        banco.atualizar_usuario(ana["id"], {"permissoes": ["pedidos"]}, por=ana)
    outro = banco.criar_usuario({"nome": "Gerente", "login": "ger", "senha": "1234", "permissoes": ["usuarios"]}, por=ana)
    banco.atualizar_usuario(ana["id"], {"permissoes": ["pedidos"]}, por=ana)
    assert banco.obter_usuario(ana["id"])["permissoes"] == ["pedidos"]
    assert outro["ativo"]


def test_trocar_propria_senha(banco, ana):
    with pytest.raises(ErroNegocio, match="atual incorreta"):
        banco.trocar_propria_senha(ana, "errada", "9999")
    banco.trocar_propria_senha(ana, "1234", "9999")
    assert banco.autenticar("ana", "9999")


# --- Auditoria ------------------------------------------------------------

def test_tudo_que_o_usuario_faz_fica_no_historico(banco, ana):
    p = banco.criar_produto({"nome": "Café", "preco_centavos": 500}, por=ana)
    banco.atualizar_produto(p["id"], {"preco_centavos": 600}, por=ana)
    pedido = banco.criar_pedido([{"produto_id": p["id"], "quantidade": 2}], por=ana)
    banco.chamar(pedido["id"], por=ana)
    banco.criar_mesa("7", por=ana)
    banco.salvar_config({"nome_loja": "Bar do Zé"}, por=ana)
    registros = banco.listar_auditoria("2000-01-01", "2100-01-01", usuario_id=ana["id"])
    por_acao = {r["acao"]: r for r in registros}
    assert "R$ 5,00 → R$ 6,00" in por_acao["Alterou produto"]["detalhes"]
    assert "2x Café" in por_acao["Lançou pedido"]["detalhes"]
    assert por_acao["Lançou pedido"]["pedido_id"] == pedido["id"]
    assert "Chamou no painel" in por_acao and "Criou mesa" in por_acao
    assert "Bar do Zé" in por_acao["Alterou configurações"]["detalhes"]
    assert all(r["usuario_nome"] == "Ana" for r in registros)
    # busca por texto
    assert [r["acao"] for r in banco.listar_auditoria("2000-01-01", "2100-01-01", busca="criou mesa")] == ["Criou mesa"]


def test_falha_desfaz_tudo_inclusive_o_historico(banco, ana):
    """A ação e o registro no histórico são gravados juntos: se der erro no
    meio, nada fica pela metade."""
    pedido = _pedido(banco, _produto(banco))
    banco.abrir_caixa(0, ana)
    antes = len(banco.listar_auditoria("2000-01-01", "2100-01-01"))
    with pytest.raises(ErroNegocio):
        banco.receber([pedido["id"]], [{"forma": "pix", "valor": 100}], ana)
    assert banco.obter_pedido(pedido["id"])["pago"] is False
    assert len(banco.listar_auditoria("2000-01-01", "2100-01-01")) == antes


def test_pedido_do_cliente_aparece_como_cliente_da_mesa(banco):
    p = _produto(banco)
    banco.criar_pedido([{"produto_id": p["id"]}], origem="qrcode", mesa="4", por={"id": None, "nome": "Cliente (mesa 4)"})
    banco.chamar_garcom("4", "conta")
    nomes = {r["usuario_nome"] for r in banco.listar_auditoria("2000-01-01", "2100-01-01")}
    assert "Cliente (mesa 4)" in nomes


# --- Caixa --------------------------------------------------------------------

def test_receber_exige_caixa_aberto(banco, ana):
    pedido = _pedido(banco, _produto(banco))
    with pytest.raises(ErroNegocio, match="fechado"):
        banco.receber([pedido["id"]], [{"forma": "dinheiro", "valor": 2500}], ana)


def test_abrir_caixa_duas_vezes(banco, ana):
    banco.abrir_caixa(10000, ana)
    with pytest.raises(ErroNegocio, match="já está aberto"):
        banco.abrir_caixa(0, ana)


def test_receber_conta_da_mesa_dividida_com_troco_e_desconto(banco, ana):
    p = _produto(banco, preco=3000)
    a = _pedido(banco, p, mesa="4")
    b = _pedido(banco, p, qtd=2, mesa="4")
    contas = banco.contas_abertas()
    assert contas == [{"chave": "mesa:4", "titulo": "Mesa 4", "pedidos": contas[0]["pedidos"], "total": 9000}]

    banco.abrir_caixa(5000, ana)
    # total 9000 - 500 desconto + 900 taxa = 9400; pix 4000 + dinheiro entregue 6000 => troco 600
    rec = banco.receber([a["id"], b["id"]], [{"forma": "pix", "valor": 4000}, {"forma": "dinheiro", "valor": 6000}],
                        ana, desconto=500, acrescimo=900)
    assert rec["total"] == 9400 and rec["troco"] == 600
    assert {f["forma"]: f["valor"] for f in rec["formas"]} == {"pix": 4000, "dinheiro": 5400}
    assert banco.contas_abertas() == []
    assert banco.obter_pedido(a["id"])["pago"] is True
    with pytest.raises(ErroNegocio, match="já foi pago"):
        banco.receber([a["id"]], [{"forma": "pix", "valor": 3000}], ana)


def test_receber_validacoes(banco, ana):
    p = _produto(banco, preco=1000)
    pedido = _pedido(banco, p)
    banco.abrir_caixa(0, ana)
    with pytest.raises(ErroNegocio, match="Falta receber R\\$ 2,00"):
        banco.receber([pedido["id"]], [{"forma": "pix", "valor": 800}], ana)
    with pytest.raises(ErroNegocio, match="Só dinheiro pode ter troco"):
        banco.receber([pedido["id"]], [{"forma": "credito", "valor": 1500}], ana)
    with pytest.raises(ErroNegocio, match="desconto"):
        banco.receber([pedido["id"]], [{"forma": "pix", "valor": 0}], ana, desconto=2000)
    with pytest.raises(ErroNegocio, match="inválida"):
        banco.receber([pedido["id"]], [{"forma": "bitcoin", "valor": 1000}], ana)
    with pytest.raises(ErroNegocio):
        banco.receber([pedido["id"]], [{"forma": "pix", "valor": -5}], ana)
    # desconto total (cortesia) é permitido
    assert banco.receber([pedido["id"]], [], ana, desconto=1000)["total"] == 0


def test_pedido_pago_nao_pode_ser_cancelado_sem_estorno(banco, ana):
    pedido = _pedido(banco, _produto(banco, preco=1000))
    banco.abrir_caixa(0, ana)
    rec = banco.receber([pedido["id"]], [{"forma": "pix", "valor": 1000}], ana)
    with pytest.raises(ErroNegocio, match="Estorne"):
        banco.mudar_status(pedido["id"], "cancelado", por=ana, motivo="x")
    with pytest.raises(ErroNegocio, match="motivo"):
        banco.estornar_recebimento(rec["id"], "", ana)
    banco.estornar_recebimento(rec["id"], "lançado errado", ana)
    assert banco.obter_pedido(pedido["id"])["pago"] is False
    with pytest.raises(ErroNegocio, match="já foi estornado"):
        banco.estornar_recebimento(rec["id"], "de novo", ana)
    banco.mudar_status(pedido["id"], "cancelado", por=ana, motivo="cliente foi embora")


def test_estorno_so_no_caixa_aberto(banco, ana):
    pedido = _pedido(banco, _produto(banco, preco=1000))
    banco.abrir_caixa(0, ana)
    rec = banco.receber([pedido["id"]], [{"forma": "pix", "valor": 1000}], ana)
    banco.fechar_caixa(0, "", ana)
    banco.abrir_caixa(0, ana)
    with pytest.raises(ErroNegocio, match="caixa que está aberto"):
        banco.estornar_recebimento(rec["id"], "x", ana)


def test_fechamento_calcula_dinheiro_esperado_e_diferenca(banco, ana):
    p = _produto(banco, preco=2000)
    banco.abrir_caixa(10000, ana)                        # fundo R$ 100
    for forma in ("dinheiro", "dinheiro", "pix", "credito"):
        banco.receber([_pedido(banco, p)["id"]], [{"forma": forma, "valor": 2000}], ana)
    estornado = banco.receber([_pedido(banco, p)["id"]], [{"forma": "dinheiro", "valor": 5000}], ana)  # troco 30
    banco.estornar_recebimento(estornado["id"], "erro", ana)
    banco.movimentar_caixa("suprimento", 3000, "reforço de troco", ana)  # +30
    banco.movimentar_caixa("sangria", 5000, "depósito", ana)             # -50
    with pytest.raises(ErroNegocio, match="Sangria maior"):
        banco.movimentar_caixa("sangria", 999999, "x", ana)
    with pytest.raises(ErroNegocio, match="motivo"):
        banco.movimentar_caixa("sangria", 100, "", ana)

    resumo = banco.resumo_sessao(banco.sessao_aberta()["id"])
    assert resumo["total_vendas"] == 8000 and resumo["qtd_vendas"] == 4
    assert resumo["por_forma"]["dinheiro"] == 4000 and resumo["por_forma"]["pix"] == 2000
    assert resumo["qtd_estornos"] == 1
    # 100 + 40 (vendas em dinheiro) + 30 - 50 = 120
    assert resumo["esperado_dinheiro"] == 12000

    fechado = banco.fechar_caixa(11500, "faltou troco", ana)
    assert fechado["diferenca"] == -500 and fechado["valor_contado"] == 11500 and not fechado["aberto"]
    assert banco.sessao_aberta() is None
    detalhes = banco.listar_auditoria("2000-01-01", "2100-01-01", busca="Fechou")[0]["detalhes"]
    assert "FALTA de R$ 5,00" in detalhes


def test_relatorio_do_periodo(banco, ana, relogio):
    burger = _produto(banco, preco=2500)
    suco = _produto(banco, "Suco", 800)
    banco.abrir_caixa(0, ana)
    banco.receber([banco.criar_pedido([{"produto_id": burger["id"], "quantidade": 2},
                                       {"produto_id": suco["id"], "quantidade": 1}])["id"]],
                  [{"forma": "pix", "valor": 5800}], ana)
    beto = banco.criar_usuario({"nome": "Beto", "login": "beto", "senha": "1234", "permissoes": ["receber"]}, por=ana)
    beto = {"id": beto["id"], "nome": "Beto"}
    banco.receber([_pedido(banco, suco)["id"]], [{"forma": "dinheiro", "valor": 1000}], beto)
    cancelado = _pedido(banco, burger)
    banco.mudar_status(cancelado["id"], "cancelado", por=ana, motivo="teste")
    _pedido(banco, suco)  # fica a receber
    relogio.ts += 86400   # outro dia, fora do período de "hoje"
    banco.receber([_pedido(banco, burger)["id"]], [{"forma": "pix", "valor": 2500}], ana)

    from datetime import datetime
    dia1 = datetime.fromtimestamp(relogio.ts - 86400).strftime("%Y-%m-%d")
    dia2 = datetime.fromtimestamp(relogio.ts).strftime("%Y-%m-%d")
    r = banco.relatorio(dia1, dia1)
    assert r["total_vendas"] == 6600 and r["qtd_vendas"] == 2 and r["ticket_medio"] == 3300
    assert r["por_forma"]["pix"] == 5800 and r["por_forma"]["dinheiro"] == 800
    assert {p["nome"]: p["quantidade"] for p in r["por_produto"]} == {"X-Burger": 2, "Suco": 2}
    assert {u["nome"]: u["valor"] for u in r["por_usuario"]} == {"Ana": 5800, "Beto": 800}
    assert [c["motivo_cancelamento"] for c in r["cancelados"]] == ["teste"]
    assert r["a_receber"] == {"quantidade": 1, "total": 800}
    assert len(r["sessoes"]) == 1
    assert banco.relatorio(dia1, dia2)["total_vendas"] == 9100
    with pytest.raises(ErroNegocio):
        banco.relatorio(dia2, dia1)

    planilha = banco.vendas_csv(dia1, dia2)
    assert planilha.startswith("﻿Data;") and "Beto" in planilha and "58,00" in planilha
    assert len(planilha.strip().splitlines()) == 4


# --- Banco antigo, backup e configurações -------------------------------------

def test_abre_banco_da_versao_1_sem_perder_dados(tmp_path):
    caminho = tmp_path / "v1.db"
    conn = sqlite3.connect(caminho)
    conn.executescript("""
        CREATE TABLE pedidos (id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, dia TEXT NOT NULL,
            prefixo TEXT NOT NULL DEFAULT '', numero INTEGER NOT NULL, codigo TEXT NOT NULL, origem TEXT NOT NULL,
            mesa TEXT NOT NULL DEFAULT '', cliente TEXT NOT NULL DEFAULT '', observacao TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, total_centavos INTEGER NOT NULL DEFAULT 0, guiche TEXT NOT NULL DEFAULT '',
            chamada_seq INTEGER, impressao TEXT NOT NULL DEFAULT '', criado_em REAL NOT NULL,
            atualizado_em REAL NOT NULL, pronto_em REAL, chamado_em REAL);
        INSERT INTO pedidos (tipo, dia, numero, codigo, origem, status, total_centavos, criado_em, atualizado_em)
            VALUES ('pedido', '2026-09-01', 1, '1', 'caixa', 'entregue', 1500, 1, 1),
                   ('senha', '2026-09-01', 1, 'N001', 'totem', 'novo', 0, 1, 1);
        CREATE TABLE config (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
        INSERT INTO config VALUES ('pin_hash', '"abc"'), ('nome_loja', '"Loja Antiga"');
    """)
    conn.commit()
    conn.close()

    banco = Banco(caminho)
    assert banco.obter_pedido(1)["total_centavos"] == 1500 and banco.obter_pedido(1)["pago"] is False
    assert banco.config()["nome_loja"] == "Loja Antiga"
    assert "pin_hash" not in banco.config()
    # senhas antigas não aparecem como contas a receber
    assert [c["titulo"] for c in banco.contas_abertas()] == ["Pedido nº 1"]


def test_backup_consistente(banco, ana, tmp_path):
    _produto(banco)
    destino = tmp_path / "backup" / "copia.db"
    banco.fazer_backup(destino)
    copia = Banco(destino)
    assert [p["nome"] for p in copia.listar_produtos()] == ["X-Burger"]
    assert copia.existe_usuario()


def test_config_tipos_e_chaves_desconhecidas(banco):
    banco.salvar_config({"historico_painel": "5", "som_chamada": 0, "chave_estranha": 1, "nome_loja": " Bar do Zé "})
    cfg = banco.config()
    assert cfg["historico_painel"] == 5 and cfg["som_chamada"] is False and cfg["nome_loja"] == "Bar do Zé"
    assert "chave_estranha" not in cfg
    with pytest.raises(ErroNegocio):
        banco.salvar_config({"historico_painel": "abc"})
    banco.secret_key()
    assert "secret_key" not in banco.config_publica()


def test_excluir_produto_mantem_historico(banco):
    p = _produto(banco)
    pedido = _pedido(banco, p)
    banco.excluir_produto(p["id"])
    assert banco.obter_pedido(pedido["id"])["itens"][0]["nome"] == "X-Burger"


def test_mover_midia(banco):
    a = banco.adicionar_midia("a.jpg", "foto")
    b = banco.adicionar_midia("b.jpg", "foto")
    banco.mover_midia(b["id"], -1)
    assert [m["arquivo"] for m in banco.listar_midias()] == ["b.jpg", "a.jpg"]
    banco.atualizar_midia(a["id"], {"ativo": False, "duracao": "12"})
    assert [m["arquivo"] for m in banco.listar_midias(somente_ativas=True)] == ["b.jpg"]


# --- Itens que não vão para a cozinha -----------------------------------------

def test_pedido_so_com_itens_prontos_nao_passa_pela_cozinha(banco, ana):
    lata = _produto(banco, "Refrigerante lata", 600, vai_cozinha=False)
    burger = _produto(banco)
    so_bebida = _pedido(banco, lata, qtd=2, mesa="3", por=ana)
    assert so_bebida["status"] == "pronto" and so_bebida["pronto_em"] and so_bebida["vai_cozinha"] is False
    misto = banco.criar_pedido([{"produto_id": lata["id"]}, {"produto_id": burger["id"]}])
    assert misto["status"] == "novo" and misto["vai_cozinha"] is True
    assert [i["vai_cozinha"] for i in misto["itens"]] == [False, True]
    # mudar o produto depois não altera pedidos já feitos
    banco.atualizar_produto(lata["id"], {"vai_cozinha": True}, por=ana)
    assert banco.obter_pedido(misto["id"])["itens"][0]["vai_cozinha"] is False
    detalhes = banco.listar_auditoria("2000-01-01", "2100-01-01", busca="sem preparo")
    assert detalhes and "Nº 1" in detalhes[0]["detalhes"]


def test_marcar_categoria_inteira(banco, ana):
    _produto(banco, "Coca", 600, categoria="Bebidas")
    _produto(banco, "Suco", 900, categoria="Bebidas")
    _produto(banco, "X-Burger")
    assert banco.definir_cozinha_categoria("Bebidas", False, por=ana) == 2
    assert {p["nome"]: p["vai_cozinha"] for p in banco.listar_produtos()} == {"Coca": False, "Suco": False, "X-Burger": True}


def test_origem_garcom_e_invalida(banco):
    p = _produto(banco)
    assert banco.criar_pedido([{"produto_id": p["id"]}], origem="garcom", mesa="2")["origem"] == "garcom"
    with pytest.raises(ErroNegocio):
        banco.criar_pedido([{"produto_id": p["id"]}], origem="hacker")


def test_admin_antigo_ganha_as_permissoes_novas(tmp_path):
    """Quem administrava usuários na 2.0.0 recebe 'garcom' e 'estornar'
    (antes o estorno vinha junto com 'cancelar'); os outros não mudam."""
    import json
    caminho = tmp_path / "v200.db"
    banco = Banco(caminho)
    with banco.lock:
        banco.conn.execute("DELETE FROM config WHERE chave = 'versao_permissoes'")
        for login, perms in (("dono", ["pedidos", "cancelar", "usuarios"]), ("caixa", ["pedidos", "cancelar"])):
            banco.conn.execute("INSERT INTO usuarios (nome, login, senha_hash, permissoes, criado_em) VALUES (?, ?, 'x', ?, 0)",
                               (login, login, json.dumps(perms)))
        banco.conn.commit()
    reaberto = Banco(caminho)
    perms = {u["login"]: set(u["permissoes"]) for u in reaberto.listar_usuarios()}
    assert {"garcom", "estornar"} <= perms["dono"]
    assert perms["caixa"] == {"pedidos", "cancelar"}
    # roda uma vez só: se o admin tirar depois, não volta sozinho
    dono = [u for u in reaberto.listar_usuarios() if u["login"] == "dono"][0]
    reaberto.atualizar_usuario(dono["id"], {"permissoes": ["usuarios"]})
    assert Banco(caminho).obter_usuario(dono["id"])["permissoes"] == ["usuarios"]


# --- Clientes, comandas, aniversários e campanhas ---------------------------------

from datetime import datetime as _dt

from comandas.banco import normalizar_telefone, proximo_aniversario, validar_cpf


def test_validacoes_de_telefone_cpf():
    assert normalizar_telefone("(11) 98765-4321") == "11987654321"
    assert normalizar_telefone("+55 11 3333-4444") == "1133334444"
    assert normalizar_telefone("98765-4321", "21") == "21987654321"
    assert normalizar_telefone("011 98765-4321") == "11987654321"       # prefixo 0 de operadora
    for ruim in ("98765-4321", "123", "(01) 98765-4321", "(11) 8765-43210", "(11) 9876-5432", "(10) 98765-4321"):
        with pytest.raises(ErroNegocio, match="Telefone"):
            normalizar_telefone(ruim)
    assert validar_cpf("529.982.247-25") == "52998224725"
    assert validar_cpf("") is None
    for ruim in ("529.982.247-24", "111.111.111-11", "123"):
        with pytest.raises(ErroNegocio, match="CPF"):
            validar_cpf(ruim)


def test_aniversario_29_de_fevereiro():
    data, idade = proximo_aniversario("2000-02-29", _dt(2027, 2, 1))
    assert data == _dt(2027, 2, 28) and idade == 27
    data, _ = proximo_aniversario("1990-03-10", _dt(2026, 3, 11))
    assert data == _dt(2027, 3, 10)


def _cliente(banco, nome="Maria Silva", telefone="11987654321", **extra):
    return banco.criar_cliente({"nome": nome, "telefone": telefone, **extra})


def test_cadastro_exige_nome_e_telefone_e_nao_duplica(banco, ana):
    with pytest.raises(ErroNegocio, match="nome"):
        banco.criar_cliente({"telefone": "11987654321"}, por=ana)
    with pytest.raises(ErroNegocio, match="Telefone"):
        banco.criar_cliente({"nome": "Maria"}, por=ana)
    maria = _cliente(banco, cpf="529.982.247-25", nascimento="10/03/1990", aceita_mensagens=True)
    assert maria["nascimento"] == "1990-03-10" and maria["consentimento_em"] and maria["cpf"] == "52998224725"
    with pytest.raises(ErroNegocio, match="esse telefone: Maria Silva"):
        _cliente(banco, "Outra", "(11) 98765-4321")
    with pytest.raises(ErroNegocio, match="esse CPF"):
        _cliente(banco, "Outra", "11911112222", cpf="52998224725")
    with pytest.raises(ErroNegocio, match="nascimento"):
        _cliente(banco, "Futuro", "11911112222", nascimento="2999-01-01")


def test_busca_e_privacidade_do_cpf(banco):
    _cliente(banco, cpf="52998224725")
    assert banco.buscar_clientes("9876")[0]["nome"] == "Maria Silva"
    assert banco.buscar_clientes("maria")[0]["cpf"] is None          # entrada não vê CPF
    assert banco.buscar_clientes("529982", com_cpf=True)[0]["cpf_formatado"] == "529.982.247-25"


def test_comanda_completa(banco, ana, relogio):
    maria = _cliente(banco)
    p = _produto(banco, preco=1500)
    k = banco.abrir_comanda(maria["id"], por=ana)
    assert k["numero"] == "1" and k["aberta"]
    with pytest.raises(ErroNegocio, match="já está com a comanda 1"):
        banco.abrir_comanda(maria["id"], por=ana)
    joao = _cliente(banco, "João", "11911112222")
    with pytest.raises(ErroNegocio, match="já está em uso"):
        banco.abrir_comanda(joao["id"], numero="1", por=ana)
    assert banco.abrir_comanda(joao["id"], por=ana)["numero"] == "2"

    pedido = banco.criar_pedido([{"produto_id": p["id"], "quantidade": 2}], comanda_id=k["id"], por=ana)
    assert pedido["cliente"] == "Maria" and pedido["comanda_numero"] == "1"
    assert any(c["titulo"] == "Comanda 1 · Maria Silva" and c["total"] == 3000 for c in banco.contas_abertas())
    with pytest.raises(ErroNegocio, match="a receber"):
        banco.fechar_comanda(k["id"], por=ana)

    banco.abrir_caixa(0, ana)
    rec = banco.receber([pedido["id"]], [{"forma": "pix", "valor": 3000}], ana)
    assert "Comanda 1" in rec["descricao"]
    assert banco.obter_comanda(k["id"])["aberta"] is False          # pagou: fecha sozinha
    with pytest.raises(ErroNegocio, match="já foi fechada"):
        banco.criar_pedido([{"produto_id": p["id"]}], comanda_id=k["id"])
    # o cartão nº 1 fica livre para o próximo cliente
    ze = _cliente(banco, "Zé", "11933334444")
    assert banco.abrir_comanda(ze["id"], por=ana)["numero"] == "1"

    banco.estornar_recebimento(rec["id"], "erro", ana)
    assert banco.obter_comanda(k["id"])["aberta"] is True           # estorno reabre

    # quem saiu sem consumir
    banco.fechar_comanda(banco.listar_comandas()[1]["id"], por=ana)
    acoes = [a["acao"] for a in banco.listar_auditoria("2000-01-01", "2100-01-01")]
    assert "Abriu comanda" in acoes and "Fechou comanda" in acoes and "Cadastrou cliente" in acoes


def test_listagem_de_clientes_com_visitas_e_gasto(banco, ana):
    maria = _cliente(banco)
    p = _produto(banco, preco=2000)
    banco.abrir_caixa(0, ana)
    for _ in range(2):
        k = banco.abrir_comanda(maria["id"], por=ana)
        pedido = banco.criar_pedido([{"produto_id": p["id"]}], comanda_id=k["id"], por=ana)
        banco.receber([pedido["id"]], [{"forma": "pix", "valor": 2000}], ana)
    c = banco.listar_clientes()[0]
    assert c["visitas"] == 2 and c["total_gasto"] == 4000 and c["ultima_visita"]
    planilha = banco.clientes_csv()
    assert planilha.startswith("﻿Nome;") and "Maria Silva" in planilha and "40,00" in planilha


def test_aniversariantes(banco, relogio):
    hoje = _dt.fromtimestamp(relogio.ts)
    from datetime import timedelta as _td
    em3 = hoje + _td(days=3)
    _cliente(banco, "Hoje", "11911110001", nascimento=hoje.replace(year=1990).strftime("%Y-%m-%d"), aceita_mensagens=True)
    _cliente(banco, "Em três dias", "11911110002", nascimento=em3.replace(year=1985).strftime("%Y-%m-%d"))
    _cliente(banco, "Longe", "11911110003", nascimento=(hoje + _td(days=40)).replace(year=1980).strftime("%Y-%m-%d"))
    lista = banco.aniversariantes(7)
    assert [(c["nome"], c["faltam_dias"]) for c in lista] == [("Hoje", 0), ("Em três dias", 3)]
    assert lista[0]["idade"] == hoje.year - 1990
    assert [c["nome"] for c in banco.aniversariantes(0)] == ["Hoje"]
    assert banco.obter_cliente(lista[0]["id"])["aniversario_hoje"] is True


def test_campanha_so_para_quem_autorizou(banco, ana):
    sim = _cliente(banco, "Autorizou", "11911110001", aceita_mensagens=True)
    _cliente(banco, "Não autorizou", "11911110002")
    publico = banco.publico_campanha("todos", "Promo sexta")
    assert [c["nome"] for c in publico] == ["Autorizou"] and publico[0]["enviado_em"] is None
    banco.registrar_mensagem(sim["id"], "Promo sexta", "Olá!", por=ana)
    assert banco.publico_campanha("todos", "Promo sexta")[0]["enviado_em"]
    assert banco.publico_campanha("todos", "Outra")[0]["enviado_em"] is None
    nao = banco.listar_clientes("Não")[0]
    with pytest.raises(ErroNegocio, match="não autorizou"):
        banco.registrar_mensagem(nao["id"], "Promo sexta", "Olá!", por=ana)
    with pytest.raises(ErroNegocio, match="nome para a campanha"):
        banco.publico_campanha("todos", "")
    # desautorizar tira da lista
    banco.atualizar_cliente(sim["id"], {"aceita_mensagens": False}, por=ana)
    assert banco.publico_campanha("todos", "Promo sexta") == []


def test_apagar_dados_do_cliente_lgpd(banco, ana):
    maria = _cliente(banco, cpf="52998224725", nascimento="1990-03-10")
    k = banco.abrir_comanda(maria["id"], por=ana)
    with pytest.raises(ErroNegocio, match="comanda aberta"):
        banco.remover_dados_cliente(maria["id"], por=ana)
    banco.fechar_comanda(k["id"], por=ana)
    banco.remover_dados_cliente(maria["id"], por=ana)
    apagado = banco.obter_cliente(maria["id"])
    assert apagado["nome"] == "Cliente removido" and apagado["cpf"] is None and apagado["nascimento"] is None
    assert banco.listar_clientes() == [] and banco.buscar_clientes("maria") == []
    assert banco.obter_comanda(k["id"])["cliente_nome"] == "Cliente removido"
    # o mesmo telefone pode ser cadastrado de novo
    assert _cliente(banco)["nome"] == "Maria Silva"


def test_permissoes_novas_para_admin_antigo(tmp_path):
    import json
    caminho = tmp_path / "v210.db"
    banco = Banco(caminho)
    with banco.lock:
        banco.conn.execute("UPDATE config SET valor = '2' WHERE chave = 'versao_permissoes'")
        banco.conn.execute("INSERT INTO usuarios (nome, login, senha_hash, permissoes, criado_em) VALUES ('Dono', 'dono', 'x', ?, 0)",
                           (json.dumps(["usuarios", "garcom", "estornar"]),))
        banco.conn.commit()
    assert {"comandas", "clientes"} <= set(Banco(caminho).listar_usuarios()[0]["permissoes"])


# --- Tela do bar ---------------------------------------------------------------

def _produtos_bar(banco):
    lanche = banco.criar_produto({"nome": "X-Burger", "preco_centavos": 2500, "destino": "cozinha"})
    chope = banco.criar_produto({"nome": "Chope", "preco_centavos": 1200, "destino": "bar"})
    lata = banco.criar_produto({"nome": "Refri lata", "preco_centavos": 600, "destino": "nenhum"})
    return lanche, chope, lata


def test_bar_sem_tela_so_imprime_e_nao_segura_o_pedido(banco):
    lanche, chope, _ = _produtos_bar(banco)
    p = banco.criar_pedido([{"produto_id": chope["id"]}])
    assert p["status"] == "pronto" and p["preparo"] == {} and p["setores"] == ["bar"]
    p = banco.criar_pedido([{"produto_id": chope["id"]}, {"produto_id": lanche["id"]}])
    assert p["status"] == "novo" and p["preparo"] == {"cozinha": "novo"}


def test_tela_do_bar_e_cozinha_cada_uma_com_seu_pronto(banco, ana):
    banco.salvar_config({"tela_bar": True})
    lanche, chope, lata = _produtos_bar(banco)
    so_bar = banco.criar_pedido([{"produto_id": chope["id"]}, {"produto_id": lata["id"]}])
    assert so_bar["status"] == "novo" and so_bar["preparo"] == {"bar": "novo"}
    assert banco.mudar_status(so_bar["id"], "pronto", por=ana, setor="bar")["status"] == "pronto"

    p = banco.criar_pedido([{"produto_id": chope["id"]}, {"produto_id": lanche["id"]}])
    assert p["preparo"] == {"cozinha": "novo", "bar": "novo"}
    p = banco.mudar_status(p["id"], "preparando", por=ana, setor="cozinha")
    assert p["status"] == "preparando" and p["preparo"] == {"cozinha": "preparando", "bar": "novo"}
    p = banco.mudar_status(p["id"], "pronto", por=ana, setor="bar")
    assert p["status"] == "preparando"  # a cozinha ainda não terminou
    p = banco.mudar_status(p["id"], "pronto", por=ana, setor="cozinha")
    assert p["status"] == "pronto" and p["pronto_em"]
    # pronto por engano no bar: volta para a fila só do bar
    p = banco.mudar_status(p["id"], "preparando", por=ana, setor="bar")
    assert p["status"] == "preparando" and p["preparo"] == {"cozinha": "pronto", "bar": "preparando"}
    with pytest.raises(ErroNegocio):
        banco.mudar_status(so_bar["id"], "pronto", setor="cozinha")  # não tem nada da cozinha
    # o caixa marcando pronto vale para as duas telas
    p = banco.mudar_status(p["id"], "pronto", por=ana)
    assert p["preparo"] == {"cozinha": "pronto", "bar": "pronto"}
    banco.chamar(p["id"])
    with pytest.raises(ErroNegocio):
        banco.mudar_status(p["id"], "preparando", setor="bar")
    acoes = [r["acao"] for r in banco.listar_auditoria(*([banco._dia()] * 2))]
    assert "Marcou pronto (bar)" in acoes and "Iniciou preparo (cozinha)" in acoes


def test_chamar_ao_ficar_pronto_so_quando_todas_as_telas_terminam(banco, ana):
    banco.salvar_config({"tela_bar": True, "chamar_ao_ficar_pronto": True})
    lanche, chope, _ = _produtos_bar(banco)
    p = banco.criar_pedido([{"produto_id": chope["id"]}, {"produto_id": lanche["id"]}])
    assert banco.mudar_status(p["id"], "pronto", setor="cozinha")["status"] == "preparando"
    assert banco.mudar_status(p["id"], "pronto", setor="bar")["status"] == "chamado"


def test_pedidos_na_fila_antes_da_atualizacao_continuam_na_cozinha(tmp_path):
    import sqlite3
    banco = Banco(tmp_path / "t.db")
    lanche, _, _ = _produtos_bar(banco)
    p = banco.criar_pedido([{"produto_id": lanche["id"]}])
    banco.conn.close()
    # simula o banco da versão anterior (sem as colunas de preparo por tela)
    con = sqlite3.connect(tmp_path / "t.db")
    for coluna in ("status_cozinha", "status_bar"):
        con.execute(f"ALTER TABLE pedidos DROP COLUMN {coluna}")
    con.commit()
    con.close()
    banco = Banco(tmp_path / "t.db")
    assert banco.obter_pedido(p["id"])["preparo"] == {"cozinha": "novo"}
