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


def test_principal_responde_quem_procura_na_rede(sistema, monkeypatch):
    banco, url, porta = sistema
    porta_udp = _porta_livre()
    monkeypatch.setattr(descoberta, "_destinos_broadcast", lambda: ["127.0.0.1"])
    resp = descoberta.Respondedor(lambda: {"sistema": "torres-comandas", "id": banco.id_instalacao(),
                                           "loja": "Lanchonete da Ana", "porta": porta, "versao": "x"}, porta=porta_udp)
    assert resp.iniciar()
    try:
        achados = descoberta.procurar(tempo=0.8, porta=porta_udp, varrer=False)
    finally:
        resp.parar()
    assert achados == [{"url": url, "id": banco.id_instalacao(), "loja": "Lanchonete da Ana", "versao": "x"}]


def test_sem_resposta_ao_broadcast_varre_a_faixa(sistema, monkeypatch):
    banco, url, porta = sistema
    monkeypatch.setattr(descoberta, "_procurar_udp", lambda tempo, porta: {})
    monkeypatch.setattr(descoberta, "ips_locais", lambda: ["127.0.0.5"])
    achados = descoberta.procurar(portas_varredura=(porta,))
    assert [a["id"] for a in achados] == [banco.id_instalacao()]
    assert achados[0]["url"] == f"http://127.0.0.1:{porta}"


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


def test_terminal_reencontra_o_principal_que_mudou_de_ip(sistema, tmp_path, monkeypatch):
    banco, url, porta = sistema
    m = Maquina(modo="terminal", servidor="http://127.0.0.1:1", id=banco.id_instalacao())
    p = Programa(tmp_path, m, subir_servidor=lambda: "")
    monkeypatch.setattr(descoberta, "procurar", lambda **kw: [{"url": url, "id": banco.id_instalacao(), "loja": "L", "versao": ""},
                                                              {"url": "http://outro", "id": "outro", "loja": "", "versao": ""}])
    assert p.url_inicial() == url + "/area"
    assert Maquina.carregar(tmp_path).servidor == url  # guardou o endereço novo
    # outro sistema na rede não serve
    m2 = Maquina(modo="terminal", servidor="http://127.0.0.1:1", id="sumiu")
    assert Programa(tmp_path, m2, subir_servidor=lambda: "").url_inicial() is None


def test_assistente_recebe_o_estado():
    html = Programa._html_assistente("reconectar", 'Não encontrei o principal "X" </script>')
    assert '"modo": "reconectar"' in html and "/*ESTADO*/" not in html
    assert "</script>\"" not in html  # o texto não pode fechar o <script> da página
