"""Ponto de entrada: abre o banco, sobe o servidor web em segundo plano e
coloca o ícone na bandeja do sistema."""
import argparse
import json
import logging
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from .banco import Banco
from .servidor import criar_app, rodar

NOME_APP = "TorresComandas"
PORTA_PADRAO = 8090


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


def porta_configurada(dados: Path) -> int:
    """Porta do servidor.json na pasta de dados (se o cliente precisar trocar
    por conflito com outro programa); senão, a padrão."""
    arquivo = dados / "servidor.json"
    try:
        return int(json.loads(arquivo.read_text(encoding="utf-8")).get("porta", PORTA_PADRAO))
    except FileNotFoundError:
        try:
            arquivo.write_text(json.dumps({"porta": PORTA_PADRAO}, indent=2), encoding="utf-8")
        except OSError:
            pass
    except (ValueError, OSError, AttributeError):
        pass
    return PORTA_PADRAO


def porta_ocupada(host: str, porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, porta))
            return False
        except OSError:
            return True


def main() -> None:
    dados = pasta_dados()
    parser = argparse.ArgumentParser(description="Torres Comandas")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--porta", type=int, default=None)
    parser.add_argument("--sem-bandeja", action="store_true",
                        help="roda só o servidor, sem ícone na bandeja nem abrir o navegador")
    args = parser.parse_args()
    porta = args.porta or porta_configurada(dados)

    (dados / "logs").mkdir(exist_ok=True)
    handlers = [logging.FileHandler(dados / "logs" / "comandas.log", encoding="utf-8")]
    if sys.stderr:  # no .exe sem console, stderr não existe
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    log = logging.getLogger("comandas")

    url_local = f"http://localhost:{porta}"
    url_rede = f"http://{ip_na_rede()}:{porta}"

    # Programa aberto duas vezes (ex.: clicou no atalho com ele já rodando
    # pela inicialização do Windows): só abre a tela inicial do que já está no ar.
    if porta_ocupada(args.host, porta):
        log.warning("Porta %s já está em uso — provavelmente o Torres Comandas já está aberto.", porta)
        if not args.sem_bandeja:
            webbrowser.open(url_local + "/")
        return

    banco = Banco(dados / "comandas.db")
    app = criar_app(banco, dados, url_base_padrao=url_rede)

    def servir():
        try:
            rodar(app, args.host, porta)
        except Exception:
            log.exception("O servidor web parou com erro")

    threading.Thread(target=servir, daemon=True, name="servidor").start()

    log.info("Torres Comandas rodando. Dados em %s", dados)
    for nome, caminho in (("Início / links", "/"), ("Caixa", "/caixa"), ("Cozinha", "/cozinha"),
                          ("Painel (TV)", "/painel"), ("Totem de senhas", "/totem"), ("Administração", "/admin")):
        log.info("  %-16s %s%s", nome, url_rede, caminho)

    if args.sem_bandeja:
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return

    # Na primeiríssima execução abre a tela inicial, pra quem acabou de
    # instalar achar os links. Depois disso fica só na bandeja.
    marcador = dados / ".ja_abriu"
    if not marcador.exists():
        marcador.touch()
        threading.Timer(1.5, lambda: webbrowser.open(url_local + "/")).start()

    try:
        from .bandeja import criar_bandeja
        criar_bandeja(url_local, url_rede, dados, lambda: log.info("Encerrando pelo menu da bandeja")).run()
    except Exception:
        log.exception("Não foi possível criar o ícone da bandeja; o servidor continua rodando (Ctrl+C para sair)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
