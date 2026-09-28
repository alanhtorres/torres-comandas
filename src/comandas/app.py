"""Ponto de entrada: abre o banco, sobe o servidor web e mostra os endereços."""
import argparse
import logging
import os
import socket
import sys
from pathlib import Path

from .banco import Banco
from .servidor import criar_app, rodar

NOME_APP = "TorresComandas"


def pasta_dados() -> Path:
    """%LOCALAPPDATA%\\TorresComandas no Windows, ~/.local/share/TorresComandas
    nos outros sistemas. A variável COMANDAS_DADOS muda o local (útil em testes)."""
    if os.environ.get("COMANDAS_DADOS"):
        pasta = Path(os.environ["COMANDAS_DADOS"])
    elif sys.platform == "win32":
        pasta = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / NOME_APP
    else:
        pasta = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / NOME_APP
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def ip_na_rede() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP não envia nada: só faz o sistema escolher a placa de rede usada.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Torres Comandas")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--porta", type=int, default=8090)
    args = parser.parse_args()

    dados = pasta_dados()
    (dados / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(dados / "logs" / "comandas.log", encoding="utf-8")],
    )
    log = logging.getLogger("comandas")

    base = f"http://{ip_na_rede()}:{args.porta}"
    banco = Banco(dados / "comandas.db")
    app = criar_app(banco, dados, url_base_padrao=base)

    log.info("Torres Comandas rodando. Dados em %s", dados)
    for nome, caminho in (("Início / links", "/"), ("Caixa", "/caixa"), ("Cozinha", "/cozinha"),
                          ("Painel (TV)", "/painel"), ("Totem de senhas", "/totem"), ("Administração", "/admin")):
        log.info("  %-16s %s%s", nome, base, caminho)
    rodar(app, args.host, args.porta)
