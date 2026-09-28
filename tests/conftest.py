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
