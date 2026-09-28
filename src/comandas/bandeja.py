"""Ícone na bandeja do sistema (perto do relógio do Windows): o servidor fica
rodando em segundo plano e o menu dá acesso rápido às telas."""
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from PIL import Image, ImageDraw


def imagem_icone(tamanho: int = 64) -> Image.Image:
    img = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(2, tamanho // 12)
    d.rounded_rectangle((m, m, tamanho - m, tamanho - m), radius=tamanho // 5, fill=(234, 88, 12, 255))
    # "comanda": folhinha branca com linhas
    fx0, fy0, fx1, fy1 = tamanho * 0.28, tamanho * 0.2, tamanho * 0.72, tamanho * 0.8
    d.rounded_rectangle((fx0, fy0, fx1, fy1), radius=tamanho // 14, fill=(255, 255, 255, 255))
    for i in range(3):
        y = fy0 + (fy1 - fy0) * (0.28 + i * 0.22)
        d.line((fx0 + tamanho * 0.07, y, fx1 - tamanho * 0.07, y), fill=(234, 88, 12, 255), width=max(1, tamanho // 16))
    return img


def _abrir_pasta(pasta: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(pasta))  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(pasta)])


def criar_bandeja(url_local: str, url_rede: str, pasta_dados: Path, ao_sair):
    # Importado só aqui: em sistemas sem bandeja o pystray falha já no import,
    # e o desenho do ícone (usado no build) não depende dele.
    import pystray

    def abrir(caminho):
        return lambda icon=None, item=None: webbrowser.open(url_local + caminho)

    def sair(icon, item):
        ao_sair()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir tela inicial (links de todas as telas)", abrir("/"), default=True),
        pystray.MenuItem("Abrir caixa", abrir("/caixa")),
        pystray.MenuItem("Abrir administração", abrir("/admin")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Endereço na rede: {url_rede}", None, enabled=False),
        pystray.MenuItem("Abrir pasta de dados (backup)", lambda icon, item: _abrir_pasta(pasta_dados)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair (desliga o sistema)", sair),
    )
    return pystray.Icon("torres_comandas", imagem_icone(), "Torres Comandas", menu)
