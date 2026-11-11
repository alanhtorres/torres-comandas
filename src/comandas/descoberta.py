"""Endereço do computador principal na rede da loja.

As outras máquinas e o app do garçom se ligam ao principal pelo IP dele
(ex.: 192.168.0.10), que aparece em Administração > Configurações > Conexões.
Não há busca automática: com o IP digitado funciona em qualquer rede (inclusive
com roteador repetidor ou Wi-Fi em outra faixa), sem depender de broadcast.
Nada disso usa internet.
"""
import json
import socket
import urllib.request
from typing import Optional
from urllib.parse import urlsplit

PORTA_PADRAO = 8090


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
