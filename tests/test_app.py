from comandas import app as modulo_app
from comandas.banco import Banco


def test_endereco_e_redescoberto_quando_o_ip_muda(monkeypatch):
    ips = iter(["127.0.0.1", "192.168.0.10", "192.168.0.20"])
    monkeypatch.setattr(modulo_app, "ip_na_rede", lambda: next(ips))
    endereco = modulo_app.EnderecoRede(8090, validade=0)
    # sem rede no momento (127.0.0.1): tenta de novo na próxima vez, não fica preso
    assert endereco() == "http://127.0.0.1:8090"
    assert endereco() == "http://192.168.0.10:8090"
    assert endereco() == "http://192.168.0.20:8090"


def test_endereco_fica_em_cache_dentro_da_validade(monkeypatch):
    chamadas = []
    monkeypatch.setattr(modulo_app, "ip_na_rede", lambda: chamadas.append(1) or "192.168.0.10")
    endereco = modulo_app.EnderecoRede(8090, validade=60)
    endereco()
    endereco()
    assert len(chamadas) == 1


def test_ip_na_rede_nao_quebra_sem_rede(monkeypatch):
    class SocketSemRede:
        def __init__(self, *a):
            pass

        def connect(self, *a):
            raise OSError("sem rota")

        def close(self):
            pass

    monkeypatch.setattr(modulo_app.socket, "socket", SocketSemRede)
    monkeypatch.setattr(modulo_app.socket, "gethostbyname_ex", lambda nome: (nome, [], ["127.0.1.1", "10.1.2.3"]))
    assert modulo_app.ip_na_rede() == "10.1.2.3"
    monkeypatch.setattr(modulo_app.socket, "gethostbyname_ex", lambda nome: (nome, [], ["127.0.1.1"]))
    assert modulo_app.ip_na_rede() == "127.0.0.1"


def test_backup_diario_guarda_os_ultimos_dias(tmp_path):
    banco = Banco(tmp_path / "comandas.db")
    banco.criar_produto({"nome": "Café", "preco_centavos": 500})
    pasta = tmp_path / "backups"
    pasta.mkdir()
    for dia in range(1, 6):
        (pasta / f"comandas-2026-01-0{dia}.db").write_bytes(b"antigo")
    modulo_app.backup_diario(banco, pasta, manter=3)
    arquivos = sorted(p.name for p in pasta.glob("*.db"))
    assert len(arquivos) == 3 and "comandas-2026-01-05.db" in arquivos
    hoje = [p for p in pasta.glob("*.db") if not p.name.startswith("comandas-2026-01")][0]
    assert [p["nome"] for p in Banco(hoje).listar_produtos()] == ["Café"]
    # rodar de novo no mesmo dia não duplica
    modulo_app.backup_diario(banco, pasta, manter=3)
    assert len(list(pasta.glob("*.db"))) == 3


def test_detecta_programa_ja_rodando():
    import socket
    servidor = socket.socket()
    servidor.bind(("127.0.0.1", 0))
    porta = servidor.getsockname()[1]
    assert modulo_app.ja_esta_rodando(porta) is False   # porta reservada mas ninguém atendendo
    servidor.listen(1)
    assert modulo_app.ja_esta_rodando(porta) is True
    servidor.close()
    assert modulo_app.ja_esta_rodando(porta) is False
