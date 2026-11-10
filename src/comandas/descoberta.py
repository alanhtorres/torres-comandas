"""Como as máquinas da loja se acham na rede, sem ninguém digitar endereço.

O computador principal fica "ouvindo" uma pergunta na porta UDP 8091. Quem
procura manda a pergunta para a rede inteira (broadcast) e cada principal
responde com o nome da loja e a porta do sistema. Se a rede bloquear o
broadcast, a busca testa a porta do sistema em todos os endereços da faixa
(ex.: 192.168.0.1 a 192.168.0.254). Nada disso usa internet.
"""
import json
import logging
import socket
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional
from urllib.parse import urlsplit

PORTA_DESCOBERTA = 8091
PORTA_PADRAO = 8090
PERGUNTA = b"TORRES-COMANDAS-PROCURA"

log = logging.getLogger("comandas")


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
    privados = [ip for ip in ips_locais() if _ip_privado(ip)]
    return privados[0] if privados else "127.0.0.1"


def ips_locais() -> list:
    """Endereços de rede local (IPv4) deste PC."""
    try:
        candidatos = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        candidatos = []
    return [ip for ip in dict.fromkeys(candidatos) if _ip_privado(ip)]


def normalizar(texto: str) -> Optional[str]:
    """Aceita "192.168.0.10", "192.168.0.10:8090" ou "http://192.168.0.10:8090/caixa"."""
    texto = (texto or "").strip()
    if not texto:
        return None
    if "://" not in texto:
        texto = "http://" + texto
    try:
        partes = urlsplit(texto)
        if not partes.hostname:
            return None
        return f"{partes.scheme}://{partes.hostname}:{partes.port or PORTA_PADRAO}"
    except ValueError:
        return None


def identificar(url: str, timeout: float = 2.5) -> Optional[dict]:
    """Pergunta ao endereço se ele é um Torres Comandas (rota pública /api/identificar)."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/identificar", timeout=timeout) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if dados.get("sistema") != "torres-comandas":
        return None
    return {"url": url.rstrip("/"), "id": dados.get("id", ""), "loja": dados.get("loja", ""),
            "versao": dados.get("versao", "")}


class Respondedor:
    """Roda no computador principal: responde a quem procura o sistema."""

    def __init__(self, info: Callable[[], dict], porta: int = PORTA_DESCOBERTA):
        self.info = info
        self.porta = porta
        self._parar = threading.Event()
        self._sock = None

    def iniciar(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", self.porta))
            s.settimeout(1)
        except OSError as exc:
            log.warning("Não foi possível responder às buscas na rede (porta UDP %s): %s", self.porta, exc)
            return False
        self._sock = s
        threading.Thread(target=self._laco, daemon=True, name="descoberta").start()
        return True

    def parar(self) -> None:
        self._parar.set()

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                dados, origem = self._sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                if self._parar.is_set():
                    break
                continue
            if dados.startswith(PERGUNTA):
                try:
                    self._sock.sendto(json.dumps(self.info()).encode("utf-8"), origem)
                except OSError:
                    pass
        self._sock.close()


def _destinos_broadcast() -> list:
    destinos = ["255.255.255.255", "127.0.0.1"]
    for ip in ips_locais():
        destinos.append(".".join(ip.split(".")[:3]) + ".255")
    return list(dict.fromkeys(destinos))


def _procurar_udp(tempo: float, porta: int) -> dict:
    achados = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        for destino in _destinos_broadcast():
            try:
                s.sendto(PERGUNTA, (destino, porta))
            except OSError:
                pass
        fim = threading.Event()
        threading.Timer(tempo, fim.set).start()
        while not fim.is_set():
            try:
                dados, (ip, _) = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                info = json.loads(dados.decode("utf-8"))
            except ValueError:
                continue
            if info.get("sistema") != "torres-comandas" or not info.get("id"):
                continue
            url = f"http://{ip}:{int(info.get('porta') or PORTA_PADRAO)}"
            atual = achados.get(info["id"])
            # O mesmo sistema pode responder pelo IP da rede e pelo 127.0.0.1
            # (quando está neste mesmo PC): fica o da rede, que vale para todos.
            if atual is None or atual["url"].startswith("http://127."):
                achados[info["id"]] = {"url": url, "id": info["id"], "loja": info.get("loja", ""),
                                       "versao": info.get("versao", "")}
    finally:
        s.close()
    return achados


def _varrer_faixa(portas) -> dict:
    """Plano B: testa a porta do sistema em todos os endereços da faixa."""
    alvos = []
    for ip in ips_locais():
        prefixo = ".".join(ip.split(".")[:3]) + "."
        alvos += [(prefixo + str(n), p) for n in range(1, 255) for p in portas]

    def testar(alvo):
        host, porta = alvo
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            if s.connect_ex((host, porta)) != 0:
                return None
        return identificar(f"http://{host}:{porta}")

    achados = {}
    with ThreadPoolExecutor(max_workers=64) as pool:
        for info in pool.map(testar, alvos):
            if info:
                achados.setdefault(info["id"], info)
    return achados


def procurar(tempo: float = 1.5, porta: int = PORTA_DESCOBERTA, portas_varredura=(PORTA_PADRAO,),
             varrer: bool = True) -> list:
    """Sistemas Torres Comandas na rede: [{"url", "id", "loja", "versao"}]."""
    achados = _procurar_udp(tempo, porta)
    if not achados and varrer:
        achados = _varrer_faixa(portas_varredura)
    return sorted(achados.values(), key=lambda s: (s["loja"].lower(), s["url"]))
