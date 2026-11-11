import json
import socket
import threading

import pytest
from werkzeug.serving import make_server

from comandas import descoberta
from comandas.banco import Banco
from comandas.maquina import Maquina
from comandas.programa import Programa
from comandas.servidor import criar_app


def _porta_livre(tipo=socket.SOCK_DGRAM):
    with socket.socket(socket.AF_INET, tipo) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def sistema(tmp_path):
    """Um Torres Comandas de verdade rodando em 127.0.0.1 (computador principal)."""
    banco = Banco(tmp_path / "t.db")
    banco.salvar_config({"nome_loja": "Lanchonete da Ana"})
    app = criar_app(banco, tmp_path, url_base_padrao="http://127.0.0.1")
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield banco, f"http://127.0.0.1:{srv.server_port}", srv.server_port
    srv.shutdown()


def test_normalizar_endereco():
    assert descoberta.normalizar("192.168.0.10") == "http://192.168.0.10:8090"
    assert descoberta.normalizar(" 192.168.0.10:8095 ") == "http://192.168.0.10:8095"
    assert descoberta.normalizar("http://192.168.0.10:8090/caixa?x=1") == "http://192.168.0.10:8090"
    assert descoberta.normalizar("") is None


def test_identificar(sistema):
    banco, url, _ = sistema
    info = descoberta.identificar(url)
    assert info == {"url": url, "id": banco.id_instalacao(), "loja": "Lanchonete da Ana", "versao": info["versao"]}
    assert descoberta.identificar("http://127.0.0.1:1") is None


def test_nao_tem_mais_busca_automatica():
    """A conexão é só pelo IP digitado (a busca na rede não funcionava em todas as lojas)."""
    for nome in ("procurar", "Respondedor", "_varrer_faixa", "PORTA_DESCOBERTA"):
        assert not hasattr(descoberta, nome)


def test_maquina_salva_e_instalacao_antiga_vira_principal(tmp_path):
    assert Maquina.carregar(tmp_path).modo is None
    (tmp_path / "comandas.db").write_bytes(b"")
    assert Maquina.carregar(tmp_path).modo == "principal"
    m = Maquina(modo="terminal", servidor="http://192.168.0.10:8090", id="abc", loja="X", tela="cozinha", tela_cheia=True)
    m.salvar(tmp_path)
    lida = Maquina.carregar(tmp_path)
    assert lida == m and lida.caminho_inicial() == "/area?tela=cozinha"
    assert Maquina(tela="painel").caminho_inicial() == "/painel"
    assert Maquina(tela="").caminho_inicial() == "/area"
    (tmp_path / "maquina.json").write_text(json.dumps({"modo": "hacker", "tela": "../x", "outro": 1}))
    lida = Maquina.carregar(tmp_path)
    assert lida.modo == "principal" and lida.tela == ""  # valores inválidos ignorados


def test_terminal_conecta_pelo_ip_salvo(sistema, tmp_path):
    banco, url, porta = sistema
    m = Maquina(modo="terminal", servidor=url, id=banco.id_instalacao())
    assert Programa(tmp_path, m, subir_servidor=lambda: "").url_inicial() == url + "/area"
    # IP que não responde: abre a tela de reconexão (None), sem procurar na rede
    m2 = Maquina(modo="terminal", servidor="http://127.0.0.1:1", id=banco.id_instalacao())
    assert Programa(tmp_path, m2, subir_servidor=lambda: "").url_inicial() is None


def test_api_conectar_pelo_ip_e_terminal_nao_vira_principal(sistema, tmp_path):
    from comandas.programa import Api
    banco, url, porta = sistema
    p = Programa(tmp_path, Maquina(), subir_servidor=lambda: "")
    api = Api(p)
    for metodo in ("procurar", "procurar_rapido", "reconfigurar"):
        assert not hasattr(api, metodo)
    r = api.conectar("127.0.0.1:1")
    assert not r["ok"] and "não respondeu em 127.0.0.1:1" in r["erro"]
    assert not api.conectar("")["ok"]
    assert api.conectar(f"127.0.0.1:{porta}") == {"ok": True}
    salvo = Maquina.carregar(tmp_path)
    assert salvo.modo == "terminal" and salvo.servidor == url and salvo.id == banco.id_instalacao()
    # Já ligado a um principal: não vira principal pelas telas
    assert api.ser_principal()["ok"] is False
    assert Maquina.carregar(tmp_path).modo == "terminal"


def test_assistente_recebe_o_estado(tmp_path):
    p = Programa(tmp_path, Maquina(modo="terminal", servidor="http://192.168.0.10:8090"), subir_servidor=lambda: "")
    html = p._html_assistente("reconectar", 'Não encontrei o principal "X" </script>')
    assert '"modo": "reconectar"' in html and "/*ESTADO*/" not in html
    assert '"ip": "192.168.0.10"' in html
    assert "</script>\"" not in html  # o texto não pode fechar o <script> da página
    assert "Procurar" not in html and "procurar(" not in html
