# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller. Rodar a partir da raiz do projeto:
    pyinstaller build_tools\\torres_comandas.spec --noconfirm
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

raiz = Path(SPECPATH).resolve().parent
src = raiz / "src"
icone = raiz / "icon" / "icon.ico"

segno_datas, segno_binaries, segno_hidden = collect_all("segno")
# Relatórios para download: reportlab (PDF, tem fontes e dados próprios) e openpyxl (Excel).
rl_datas, rl_binaries, rl_hidden = collect_all("reportlab")
xl_datas, xl_binaries, xl_hidden = collect_all("openpyxl")

# Só o backend de bandeja do sistema em que o build está rodando.
bandeja = ["pystray._win32"] if sys.platform == "win32" else ["pystray._xorg", "pystray._appindicator"]

a = Analysis(
    [str(raiz / "main.py")],
    pathex=[str(src)],
    binaries=segno_binaries + rl_binaries + xl_binaries,
    datas=[
        (str(src / "comandas" / "web" / "templates"), "comandas/web/templates"),
        (str(src / "comandas" / "web" / "static"), "comandas/web/static"),
    ] + segno_datas + rl_datas + xl_datas,
    hiddenimports=["waitress", "comandas.bandeja"] + bandeja + segno_hidden + rl_hidden + xl_hidden,
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TorresComandas",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icone) if icone.is_file() else None,
)

coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="TorresComandas")
