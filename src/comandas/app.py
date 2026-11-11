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
from datetime import datetime
from pathlib import Path

from . import __version__, descoberta
from .banco import Banco
from .descoberta import ip_na_rede
from .maquina import Maquina
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


def subir_sistema(dados: Path, host: str, porta: int) -> Banco:
    """Liga o sistema neste PC (computador principal): banco, servidor web,
    e backup diário."""
    log = logging.getLogger("comandas")
    endereco = EnderecoRede(porta)
    banco = Banco(dados / "comandas.db")
    app = criar_app(banco, dados, url_base_padrao=endereco)

    def backups():
        while True:
            try:
                backup_diario(banco, dados / "backups")
            except Exception:
                log.exception("Falha no backup automático")
            time.sleep(3600)

    threading.Thread(target=backups, daemon=True, name="backup").start()

    def servir():
        try:
            rodar(app, host, porta)
        except Exception:
            log.exception("O servidor web parou com erro")

    threading.Thread(target=servir, daemon=True, name="servidor").start()
    for _ in range(50):  # espera o servidor atender (a janela abre logo em seguida)
        if ja_esta_rodando(porta):
            break
        time.sleep(0.1)
    log.info("Torres Comandas %s rodando como computador principal em %s. Dados em %s", __version__, endereco(), dados)
    return banco


def main() -> None:
    dados = pasta_dados()
    parser = argparse.ArgumentParser(description="Torres Comandas")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--porta", type=int, default=None)
    parser.add_argument("--sem-bandeja", action="store_true",
                        help="só o sistema (computador principal), sem janela nem ícone — para testes e servidores")
    parser.add_argument("--modo", choices=("principal", "terminal"), help="define o papel deste computador")
    parser.add_argument("--servidor", help="terminal: IP (ou endereço) do computador principal")
    parser.add_argument("--tela", help="tela que esta máquina abre (caixa, cozinha, bar, painel...)")
    parser.add_argument("--teste-janela", help=argparse.SUPPRESS)  # arquivo de resultado do teste automático
    parser.add_argument("--teste-login", help=argparse.SUPPRESS)
    args = parser.parse_args()
    porta = args.porta or porta_configurada(dados)

    (dados / "logs").mkdir(exist_ok=True)
    handlers = [logging.FileHandler(dados / "logs" / "comandas.log", encoding="utf-8")]
    if sys.stderr:  # no .exe sem console, stderr não existe
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    log = logging.getLogger("comandas")

    if args.sem_bandeja:
        if ja_esta_rodando(porta):
            log.warning("Porta %s já está em uso — o Torres Comandas já está aberto neste PC.", porta)
            return
        subir_sistema(dados, args.host, porta)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return

    from .programa import Programa, avisar_instancia_aberta

    # Clicou no atalho com o programa já aberto: só mostra a janela que já existe.
    if not args.teste_janela and avisar_instancia_aberta():
        return

    maquina = Maquina.carregar(dados)
    if args.modo:
        maquina.modo = args.modo
    if args.tela is not None:
        maquina.tela = args.tela
    if args.servidor:
        url = descoberta.normalizar(args.servidor)
        info = descoberta.identificar(url) if url else None
        if info:
            maquina.servidor, maquina.id, maquina.loja = info["url"], info["id"], info["loja"]
        else:
            log.warning("Computador principal não encontrado: %s", args.servidor)
    if maquina.modo:
        maquina.salvar(dados)

    def ligar_aqui() -> str:
        if ja_esta_rodando(porta):
            log.warning("Porta %s já está em uso: usando o sistema que já está no ar neste PC.", porta)
        else:
            subir_sistema(dados, args.host, porta)
        return f"http://127.0.0.1:{porta}"

    teste = {"saida": args.teste_janela, "login": args.teste_login or "",
             "esperar_abas": bool(args.teste_login) and maquina.caminho_inicial().startswith("/area")} if args.teste_janela else None
    Programa(dados, maquina, ligar_aqui, teste=teste).rodar()
