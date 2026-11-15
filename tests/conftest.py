import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class ImpressoraFalsa:
    """Servidor TCP de verdade que recebe os bytes como uma impressora de
    rede recebe na porta 9100."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.porta = self.sock.getsockname()[1]
        self.recebidos = []
        self.thread = threading.Thread(target=self._aceitar, daemon=True)
        self.thread.start()

    def _aceitar(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                dados = b""
                while True:
                    parte = conn.recv(4096)
                    if not parte:
                        break
                    dados += parte
                self.recebidos.append(dados)

    def esperar(self, n=1, timeout=5):
        fim = time.time() + timeout
        while len(self.recebidos) < n and time.time() < fim:
            time.sleep(0.02)
        return self.recebidos

    def fechar(self):
        self.sock.close()


@pytest.fixture
def impressora_falsa():
    f = ImpressoraFalsa()
    yield f
    f.fechar()


# Desde a 3.5.0 não entra pedido com o caixa fechado. Para os testes antigos
# (que lançam pedidos sem se preocupar com o caixa) não precisarem abrir o
# caixa um por um, o caixa abre sozinho no primeiro pedido — como um caixa
# "automático" sem fundo de troco e sem registro no histórico. Se o teste
# depois abrir o caixa de verdade, esse automático some antes (enquanto não
# tiver nenhum pagamento). Teste marcado com @pytest.mark.caixa_fechado vê
# o comportamento real.
AUTOMATICO = "Caixa automático dos testes"


@pytest.fixture(autouse=True)
def caixa_automatico(request, monkeypatch):
    if request.node.get_closest_marker("caixa_fechado"):
        return
    from comandas.banco import Banco

    criar, abrir = Banco.criar_pedido, Banco.abrir_caixa

    def criar_pedido(self, *args, **kwargs):
        if not self.sessao_aberta():
            with self.lock:
                self.conn.execute("INSERT INTO sessoes_caixa (aberto_por_nome, aberto_em, valor_abertura) VALUES (?, ?, 0)",
                                  (AUTOMATICO, self.agora()))
                self.conn.commit()
        return criar(self, *args, **kwargs)

    def abrir_caixa(self, *args, **kwargs):
        sessao = self.sessao_aberta()
        if sessao and sessao["aberto_por_nome"] == AUTOMATICO:
            with self.lock:
                usado = self.conn.execute(
                    "SELECT (SELECT COUNT(*) FROM recebimentos WHERE sessao_id = ?) + "
                    "(SELECT COUNT(*) FROM movimentos_caixa WHERE sessao_id = ?) AS n", (sessao["id"], sessao["id"])).fetchone()["n"]
                if not usado:
                    self.conn.execute("DELETE FROM sessoes_caixa WHERE id = ?", (sessao["id"],))
                    self.conn.commit()
        return abrir(self, *args, **kwargs)

    monkeypatch.setattr(Banco, "criar_pedido", criar_pedido)
    monkeypatch.setattr(Banco, "abrir_caixa", abrir_caixa)


def pytest_configure(config):
    config.addinivalue_line("markers", "caixa_fechado: sem o caixa automático dos testes (pedido exige caixa aberto)")
