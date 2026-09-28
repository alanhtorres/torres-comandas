import pytest

from comandas.banco import Banco, ErroNegocio


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


def _produto(banco, nome="X-Burger", preco=2500, **extra):
    return banco.criar_produto({"nome": nome, "preco_centavos": preco, "categoria": "Lanches", **extra})


def test_pedido_calcula_total_e_guarda_copia_dos_itens(banco):
    burger = _produto(banco)
    suco = _produto(banco, "Suco", 800)
    pedido = banco.criar_pedido([
        {"produto_id": burger["id"], "quantidade": 2, "observacao": "sem cebola"},
        {"produto_id": suco["id"], "quantidade": 1},
    ], cliente="Ana")
    assert pedido["codigo"] == "1"
    assert pedido["status"] == "novo"
    assert pedido["total_centavos"] == 2 * 2500 + 800
    assert pedido["itens"][0]["observacao"] == "sem cebola"

    # mudar o preço depois não altera um pedido já feito
    banco.atualizar_produto(burger["id"], {"preco_centavos": 9999})
    assert banco.obter_pedido(pedido["id"])["total_centavos"] == 5800


def test_numeracao_reinicia_a_cada_dia(banco, relogio):
    p = _produto(banco)
    assert banco.criar_pedido([{"produto_id": p["id"]}])["codigo"] == "1"
    assert banco.criar_pedido([{"produto_id": p["id"]}])["codigo"] == "2"
    relogio.ts += 86400
    assert banco.criar_pedido([{"produto_id": p["id"]}])["codigo"] == "1"


def test_pedido_rejeita_vazio_produto_inativo_e_quantidade_invalida(banco):
    p = _produto(banco, ativo=False)
    ativo = _produto(banco, "Outro")
    with pytest.raises(ErroNegocio):
        banco.criar_pedido([])
    with pytest.raises(ErroNegocio):
        banco.criar_pedido([{"produto_id": p["id"], "quantidade": 1}])
    with pytest.raises(ErroNegocio):
        banco.criar_pedido([{"produto_id": ativo["id"], "quantidade": 0}])
    with pytest.raises(ErroNegocio):
        banco.criar_pedido([{"produto_id": "abc"}])


def test_fluxo_cozinha_pronto_chamar_entregar(banco):
    p = _produto(banco)
    pedido = banco.criar_pedido([{"produto_id": p["id"]}], cliente="João")
    banco.mudar_status(pedido["id"], "preparando")
    pronto = banco.mudar_status(pedido["id"], "pronto")
    assert pronto["status"] == "pronto" and pronto["pronto_em"]
    assert banco.chamadas_recentes() == []  # pronto ainda não aparece no painel

    chamado = banco.chamar(pedido["id"])
    assert chamado["status"] == "chamado"
    painel = banco.chamadas_recentes()
    assert [c["codigo"] for c in painel] == ["1"]
    assert painel[0]["cliente"] == "João"

    banco.mudar_status(pedido["id"], "entregue")
    assert banco.listar_pedidos() == []
    # entregue continua no histórico do painel (esmaecido)
    assert banco.chamadas_recentes()[0]["status"] == "entregue"
    with pytest.raises(ErroNegocio):
        banco.mudar_status(pedido["id"], "preparando")


def test_chamar_de_novo_sobe_para_o_topo_do_painel(banco):
    p = _produto(banco)
    a = banco.criar_pedido([{"produto_id": p["id"]}])
    b = banco.criar_pedido([{"produto_id": p["id"]}])
    banco.chamar(a["id"])
    banco.chamar(b["id"])
    assert [c["codigo"] for c in banco.chamadas_recentes()] == ["2", "1"]
    seq_antes = banco.chamadas_recentes()[1]["chamada_seq"]
    banco.chamar(a["id"])
    painel = banco.chamadas_recentes()
    assert [c["codigo"] for c in painel] == ["1", "2"]
    assert painel[0]["chamada_seq"] > seq_antes


def test_chamar_ao_ficar_pronto_automatico(banco):
    banco.salvar_config({"chamar_ao_ficar_pronto": True})
    p = _produto(banco)
    pedido = banco.criar_pedido([{"produto_id": p["id"]}])
    assert banco.mudar_status(pedido["id"], "pronto")["status"] == "chamado"


def test_cancelado_nao_pode_ser_chamado(banco):
    p = _produto(banco)
    pedido = banco.criar_pedido([{"produto_id": p["id"]}])
    banco.mudar_status(pedido["id"], "cancelado")
    with pytest.raises(ErroNegocio):
        banco.chamar(pedido["id"])


def test_senhas_preferencial_primeiro_e_guiche_libera_anterior(banco, relogio):
    n1 = banco.emitir_senha("N")
    relogio.ts += 1
    banco.emitir_senha("N")
    relogio.ts += 1
    p1 = banco.emitir_senha("P")
    assert n1["codigo"] == "N001" and p1["codigo"] == "P001"
    assert banco.resumo_senhas() == {"aguardando": {"N": 2, "P": 1}, "total": 3}

    primeira = banco.chamar_proxima_senha("1")
    assert primeira["codigo"] == "P001" and primeira["guiche"] == "1"
    segunda = banco.chamar_proxima_senha("1")
    assert segunda["codigo"] == "N001"
    # a P001 foi dada como atendida quando o guichê 1 chamou a próxima
    assert banco.obter_pedido(p1["id"])["status"] == "entregue"
    banco.chamar_proxima_senha("1")
    assert banco.chamar_proxima_senha("1") is None
    assert banco.resumo_senhas()["total"] == 0


def test_senhas_por_ordem_de_chegada_quando_sem_prioridade(banco, relogio):
    banco.salvar_config({"senha_preferencial_primeiro": False})
    banco.emitir_senha("N")
    relogio.ts += 1
    banco.emitir_senha("P")
    assert banco.chamar_proxima_senha("2")["codigo"] == "N001"


def test_senha_tipo_invalido(banco):
    with pytest.raises(ErroNegocio):
        banco.emitir_senha("X")


def test_chamado_garcom_nao_duplica_e_e_atendido(banco):
    c1 = banco.chamar_garcom("5")
    c2 = banco.chamar_garcom("5")
    assert c1["id"] == c2["id"]
    banco.chamar_garcom("5", "conta")
    assert len(banco.chamados_pendentes()) == 2
    banco.atender_chamado(c1["id"])
    assert [c["tipo"] for c in banco.chamados_pendentes("5")] == ["conta"]
    with pytest.raises(ErroNegocio):
        banco.chamar_garcom("5", "outro")


def test_mesas_tokens_unicos_lote_e_novo_token(banco):
    criadas = banco.criar_mesas_em_lote(1, 12)
    assert len(criadas) == 12
    assert len({m["token"] for m in criadas}) == 12
    # ordena numericamente
    assert [m["numero"] for m in banco.listar_mesas()][:3] == ["1", "2", "3"]
    assert banco.criar_mesas_em_lote(10, 13) and len(banco.listar_mesas()) == 13
    with pytest.raises(ErroNegocio):
        banco.criar_mesa("1")
    antiga = banco.listar_mesas()[0]
    nova = banco.novo_token_mesa(antiga["id"])
    assert nova["token"] != antiga["token"]
    assert banco.mesa_por_token(antiga["token"]) is None


def test_config_tipos_e_chaves_desconhecidas(banco):
    banco.salvar_config({"historico_painel": "5", "som_chamada": 0, "chave_estranha": 1, "nome_loja": " Bar do Zé "})
    cfg = banco.config()
    assert cfg["historico_painel"] == 5
    assert cfg["som_chamada"] is False
    assert cfg["nome_loja"] == "Bar do Zé"
    assert "chave_estranha" not in cfg
    with pytest.raises(ErroNegocio):
        banco.salvar_config({"historico_painel": "abc"})


def test_config_publica_nao_vaza_segredos(banco):
    banco.secret_key()
    banco.salvar_config({"pin_hash": "xyz"})
    publica = banco.config_publica()
    assert "pin_hash" not in publica and "secret_key" not in publica
    assert publica["pin_definido"] is True


def test_excluir_produto_mantem_historico(banco):
    p = _produto(banco)
    pedido = banco.criar_pedido([{"produto_id": p["id"]}])
    banco.excluir_produto(p["id"])
    assert banco.obter_pedido(pedido["id"])["itens"][0]["nome"] == "X-Burger"


def test_mover_midia(banco):
    a = banco.adicionar_midia("a.jpg", "foto")
    b = banco.adicionar_midia("b.jpg", "foto")
    banco.mover_midia(b["id"], -1)
    assert [m["arquivo"] for m in banco.listar_midias()] == ["b.jpg", "a.jpg"]
    banco.atualizar_midia(a["id"], {"ativo": False, "duracao": "12"})
    assert [m["arquivo"] for m in banco.listar_midias(somente_ativas=True)] == ["b.jpg"]
    assert banco.listar_midias()[1]["duracao"] == 12


def test_versao_muda_a_cada_alteracao(banco):
    v = banco.versao
    _produto(banco)
    assert banco.versao > v
