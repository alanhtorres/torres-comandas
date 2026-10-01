"""Ponto de entrada: abre o banco, sobe o servidor web em segundo plano e
coloca o ícone na bandeja do sistema."""
import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
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


def _ip_privado(ip: str) -> bool:
    return ip.startswith(("192.168.", "10.")) or (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)


def ip_na_rede() -> str:
    """IP deste PC na rede da loja. Não depende de internet: o "connect" em
    UDP não envia nada, só pergunta ao Windows qual placa de rede seria
    usada. Se nem isso der (PC sem rota padrão), procura um IP de rede
    local entre os endereços do próprio PC."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        s.close()
    try:
        candidatos = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        candidatos = []
    privados = [ip for ip in candidatos if _ip_privado(ip)]
    return privados[0] if privados else "127.0.0.1"


class EnderecoRede:
    """Endereço do servidor na rede, redescoberto a cada minuto: se o PC
    ligou antes do roteador, ou o IP mudou, os QR codes novos já saem certos
    sem precisar reiniciar o programa."""

    def __init__(self, porta: int, validade: float = 60):
        self.porta = porta
        self.validade = validade
        self._valor = None
        self._quando = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            agora = time.monotonic()
            if self._valor is None or agora - self._quando >= self.validade or "127.0.0.1" in self._valor:
                self._valor = f"http://{ip_na_rede()}:{self.porta}"
                self._quando = agora
            return self._valor


def backup_diario(banco: Banco, pasta: Path, manter: int = 30) -> None:
    """Uma cópia do banco por dia na pasta backups/, guardando os últimos
    `manter` dias. Protege contra arquivo corrompido (queda de energia,
    disco com defeito) — copie essa pasta para um pendrive de vez em quando."""
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"comandas-{datetime.now():%Y-%m-%d}.db"
    if not destino.exists():
        banco.fazer_backup(destino)
        logging.getLogger("comandas").info("Backup do dia salvo em %s", destino)
    antigos = sorted(pasta.glob("comandas-*.db"))[:-manter]
    for arquivo in antigos:
        arquivo.unlink(missing_ok=True)


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


def ja_esta_rodando(porta: int) -> bool:
    """Tem algum programa de fato atendendo nessa porta? Testa conectando
    (e não tentando ocupar a porta), porque logo depois de fechar o programa
    o sistema mantém a porta "esfriando" por um tempo — e isso não pode
    impedir o servidor de subir de novo após um reinício rápido."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", porta)) == 0


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
    endereco = EnderecoRede(porta)
    url_rede = endereco()

    # Programa aberto duas vezes (ex.: clicou no atalho com ele já rodando
    # pela inicialização do Windows): só abre a tela inicial do que já está no ar.
    if ja_esta_rodando(porta):
        log.warning("Porta %s já está em uso — provavelmente o Torres Comandas já está aberto.", porta)
        if not args.sem_bandeja:
            webbrowser.open(url_local + "/")
        return

    banco = Banco(dados / "comandas.db")
    app = criar_app(banco, dados, url_base_padrao=endereco)

    def backups():
        while True:
            try:
                backup_diario(banco, dados / "backups")
            except Exception:
                logging.getLogger("comandas").exception("Falha no backup automático")
            time.sleep(3600)

    threading.Thread(target=backups, daemon=True, name="backup").start()

    def servir():
        try:
            rodar(app, args.host, porta)
        except Exception:
            log.exception("O servidor web parou com erro")

    threading.Thread(target=servir, daemon=True, name="servidor").start()

    log.info("Torres Comandas rodando. Dados em %s", dados)
    for nome, caminho in (("Início / links", "/"), ("Caixa", "/caixa"), ("Cozinha", "/cozinha"),
                          ("Painel (TV)", "/painel"), ("Administração", "/admin")):
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
