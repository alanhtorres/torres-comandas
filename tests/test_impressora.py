import socket
import sys

import pytest

from comandas import impressora


PEDIDO = {
    "id": 1, "codigo": "42", "origem": "qrcode", "mesa": "7", "cliente": "Conceição",
    "criado_em": 1_790_000_000.0, "observacao": "Cliente alérgico a amendoim",
    "itens": [
        {"nome": "X-Salada Especial da Casa com Bacon", "quantidade": 2, "observacao": "sem cebola", "preco_centavos": 3000},
        {"nome": "Suco de maçã", "quantidade": 1, "observacao": "", "preco_centavos": 900},
    ],
}


def test_cupom_cozinha_tem_comandos_escpos_e_acentos_cp850():
    dados = impressora.cupom_cozinha(PEDIDO, "Lanchonete São João", colunas=48, codificacao="cp850")
    assert dados.startswith(impressora.INICIAR + impressora.FORMATO_PADRAO + b"\x1bt\x02")
    assert dados.endswith(impressora.CORTAR)
    assert "Conceição".encode("cp850") in dados
    assert "São João".encode("cp850") in dados
    assert b"No 42" in dados
    assert b"sem cebola" in dados
    assert "alérgico".encode("cp850") in dados


def test_cozinha_e_bar_saem_no_mesmo_formato():
    pedido = {**PEDIDO, "itens": [
        {"nome": "X-Burger", "quantidade": 1, "preco_centavos": 2500, "observacao": "", "setor": "cozinha"},
        {"nome": "X-Burger", "quantidade": 1, "preco_centavos": 2500, "observacao": "", "setor": "bar"},
    ]}
    cozinha = impressora.cupom_cozinha(pedido, "Loja")
    bar = impressora.cupom_cozinha(pedido, "Loja", setor="bar")
    # fonte A forçada (não depende do padrão gravado em cada impressora)
    assert impressora.ESC + b"M\x00" in cozinha
    assert cozinha.replace(b"COZINHA", b"BAR") == bar


def test_cupom_sem_acentos():
    dados = impressora.cupom_cozinha(PEDIDO, "Lanchonete São João", codificacao="ascii")
    assert b"Conceicao" in dados and b"Sao Joao" in dados
    assert b"\x1bt" not in dados[:5]


def test_quebra_de_linha_respeita_largura():
    c = impressora.Cupom(colunas=32)
    c.quebrar("palavra " * 20, 32)
    for linha in c.dados.split(b"\n")[1:-1]:
        assert len(linha) <= 32


def test_cupom_do_bar_so_com_os_itens_do_bar():
    pedido = {**PEDIDO, "itens": [
        {"nome": "X-Burger", "quantidade": 1, "preco_centavos": 2500, "observacao": "", "setor": "cozinha"},
        {"nome": "Chopp", "quantidade": 2, "preco_centavos": 1200, "observacao": "", "setor": "bar"},
        {"nome": "Coca lata", "quantidade": 1, "preco_centavos": 600, "observacao": "", "setor": "nenhum"},
    ]}
    bar = impressora.cupom_cozinha(pedido, "Loja", setor="bar")
    assert b"PEDIDO BAR" in bar and b"Chopp" in bar and b"X-Burger" not in bar and b"Coca" not in bar
    cozinha = impressora.cupom_cozinha(pedido, "Loja")
    assert b"PEDIDO COZINHA" in cozinha and b"X-Burger" in cozinha and b"Chopp" not in cozinha


def test_enviar_para_escolhe_rede_ou_usb(impressora_falsa, monkeypatch):
    usb = []
    monkeypatch.setattr(impressora, "enviar_windows", lambda nome, dados: usb.append(nome))
    cfg = {"impressora_bar_tipo": "rede", "impressora_bar_host": "127.0.0.1", "impressora_bar_porta": impressora_falsa.porta,
           "impressora_bar_usb": "POS-58"}
    impressora.enviar_para(cfg, "bar", b"rede")
    assert impressora_falsa.esperar() == [b"rede"] and usb == []
    impressora.enviar_para({**cfg, "impressora_bar_tipo": "usb"}, "bar", b"usb")
    assert usb == ["POS-58"]


@pytest.mark.skipif(sys.platform != "win32", reason="impressora USB só existe no Windows")
def test_usb_de_verdade_no_windows():
    nomes = impressora.listar_impressoras_windows()
    assert isinstance(nomes, list) and all(isinstance(n, str) and n for n in nomes)
    with pytest.raises(impressora.ErroImpressora, match="não encontrada"):
        impressora.enviar_windows("Impressora Que Nao Existe 123", b"x")


def test_usb_sem_nome_ou_fora_do_windows():
    with pytest.raises(impressora.ErroImpressora, match="não escolhida"):
        impressora.enviar_windows("", b"x")
    if sys.platform != "win32":
        assert impressora.listar_impressoras_windows() == []


def test_envio_real_por_tcp(impressora_falsa):
    dados = impressora.cupom_cozinha(PEDIDO, "Loja")
    impressora.enviar("127.0.0.1", impressora_falsa.porta, dados)
    assert impressora_falsa.esperar() == [dados]


def test_envio_falha_com_mensagem_clara():
    # porta fechada: nada escutando
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    with pytest.raises(impressora.ErroImpressora, match="Não foi possível imprimir"):
        impressora.enviar("127.0.0.1", porta, b"x", timeout=1)
    with pytest.raises(impressora.ErroImpressora, match="não configurado"):
        impressora.enviar("", 9100, b"x")


def test_cupom_conta_com_taxa_de_servico():
    dados = impressora.cupom_conta("Mesa 7", [PEDIDO], "Bar", taxa_servico_percentual=10)
    assert b"CONFERENCIA DE CONTA" in dados and b"Mesa 7" in dados
    assert b"R$ 69,00" in dados and b"R$ 6,90" in dados and b"R$ 75,90" in dados
    assert b"Nao e documento fiscal" in dados


def test_cupom_fechamento_mostra_diferenca():
    resumo = {
        "aberto_em": 1_790_000_000.0, "aberto_por_nome": "Ana", "fechado_em": 1_790_030_000.0, "fechado_por_nome": "Ana",
        "qtd_vendas": 3, "total_vendas": 12000, "por_forma": {"dinheiro": 5000, "pix": 7000}, "descontos": 0,
        "qtd_estornos": 0, "total_estornos": 0, "valor_abertura": 10000, "suprimentos": 0, "sangrias": 2000,
        "esperado_dinheiro": 13000, "valor_contado": 12500, "diferenca": -500,
        "movimentos": [{"tipo": "sangria", "motivo": "depósito", "valor": 2000}], "observacao": "",
    }
    dados = impressora.cupom_fechamento(resumo, "Bar", {"dinheiro": "Dinheiro", "pix": "Pix"}, colunas=32)
    assert b"FECHAMENTO DE CAIXA" in dados and b"FALTA" in dados and b"R$ 5,00" in dados
    assert b"R$ 130,00" in dados and "depósito".encode("cp850") in dados
    for linha in dados.split(b"\n"):
        limpa = linha.replace(impressora.NEGRITO_ON, b"").replace(impressora.NEGRITO_OFF, b"")
        assert len(limpa) <= 40  # cabe na bobina (com folga para comandos)
