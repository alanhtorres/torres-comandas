import socket

import pytest

from comandas import impressora


PEDIDO = {
    "id": 1, "codigo": "42", "origem": "qrcode", "mesa": "7", "cliente": "Conceição",
    "criado_em": 1_790_000_000.0, "observacao": "Cliente alérgico a amendoim",
    "itens": [
        {"nome": "X-Salada Especial da Casa com Bacon", "quantidade": 2, "observacao": "sem cebola"},
        {"nome": "Suco de maçã", "quantidade": 1, "observacao": ""},
    ],
}


def test_cupom_cozinha_tem_comandos_escpos_e_acentos_cp850():
    dados = impressora.cupom_cozinha(PEDIDO, "Lanchonete São João", colunas=48, codificacao="cp850")
    assert dados.startswith(impressora.INICIAR + b"\x1bt\x02")
    assert dados.endswith(impressora.CORTAR)
    assert "Conceição".encode("cp850") in dados
    assert "São João".encode("cp850") in dados
    assert b"No 42" in dados
    assert b"sem cebola" in dados
    assert "alérgico".encode("cp850") in dados


def test_cupom_sem_acentos():
    dados = impressora.cupom_cozinha(PEDIDO, "Lanchonete São João", codificacao="ascii")
    assert b"Conceicao" in dados and b"Sao Joao" in dados
    assert b"\x1bt" not in dados[:5]


def test_quebra_de_linha_respeita_largura():
    c = impressora.Cupom(colunas=32)
    c.quebrar("palavra " * 20, 32)
    for linha in c.dados.split(b"\n")[1:-1]:
        assert len(linha) <= 32


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


def test_cupom_senha():
    dados = impressora.cupom_senha({"codigo": "P007", "criado_em": 1_790_000_000.0}, "Lotérica", "Preferencial")
    assert b"P007" in dados and b"PREFERENCIAL" in dados
    assert impressora.TAMANHO_GIGANTE in dados
