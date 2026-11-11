"""A janela do programa: as telas do sistema numa janela própria do Windows
(WebView2, o mesmo motor do Edge), sem navegador e sem digitar endereço.

- Primeira vez: pergunta se este computador é o principal ou se conecta a
  um principal pelo IP dele. Depois disso o papel não muda mais pelas telas
  (para recomeçar, apaga-se a pasta de dados).
- Principal: liga o sistema (banco + servidor) e mostra a janela. Fechar a
  janela só a esconde: o sistema continua no ar para as outras máquinas, com
  o ícone perto do relógio.
- Terminal: mostra as telas do principal. Se o principal não responder ao
  abrir, mostra a tela de reconexão (tenta de novo sozinho, ou digita outro IP).
"""
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import __version__, descoberta
from .maquina import TELAS, Maquina

log = logging.getLogger("comandas")

PORTA_CONTROLE = 8092  # só no próprio PC: o 2º clique no atalho mostra a janela já aberta
ASSISTENTE = Path(__file__).parent / "web" / "assistente.html"


# --- Uma instância só ------------------------------------------------------------

def avisar_instancia_aberta() -> bool:
    """Se o programa já está aberto neste PC, pede para ele mostrar a janela."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_CONTROLE), timeout=1) as s:
            s.sendall(b"mostrar")
        return True
    except OSError:
        return False


def ouvir_instancia(ao_pedir: Callable[[], None]) -> None:
    def laco(srv):
        while True:
            try:
                con, _ = srv.accept()
                with con:
                    if con.recv(16) == b"mostrar":
                        ao_pedir()
            except OSError:
                continue

    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", PORTA_CONTROLE))
        srv.listen(4)
    except OSError as exc:
        log.warning("Controle de instância única indisponível: %s", exc)
        return
    threading.Thread(target=laco, args=(srv,), daemon=True, name="instancia").start()


# --- WebView2 ---------------------------------------------------------------------

def webview2_instalado() -> bool:
    """O Windows 10/11 atualizado já traz o WebView2. Sem ele, o programa abre
    as telas numa janela do Edge sem barra de endereço."""
    if sys.platform != "win32":
        return True
    import winreg
    chave = r"SOFTWARE\{}Microsoft\EdgeUpdate\Clients\{{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}}"
    for raiz, wow in ((winreg.HKEY_LOCAL_MACHINE, "WOW6432Node\\"), (winreg.HKEY_LOCAL_MACHINE, ""),
                      (winreg.HKEY_CURRENT_USER, "")):
        try:
            with winreg.OpenKey(raiz, chave.format(wow)) as k:
                versao, _ = winreg.QueryValueEx(k, "pv")
                if versao and versao != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def abrir_no_edge(url: str, tela_cheia: bool, perfil: Path) -> bool:
    """Plano B sem WebView2: janela do Edge sem barra de endereço (modo app)."""
    candidatos = [Path(os.environ.get(v, "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
                  for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    edge = next((c for c in candidatos if c.is_file()), None)
    if not edge:
        import webbrowser
        return webbrowser.open(url)
    args = [str(edge), f"--app={url}", f"--user-data-dir={perfil}", "--autoplay-policy=no-user-gesture-required",
            "--no-first-run"]
    if tela_cheia:
        args.append("--start-fullscreen")
    subprocess.Popen(args)  # noqa: S603
    return True


# --- O que a página pode pedir ao programa (window.pywebview.api) ------------------

class Api:
    def __init__(self, programa: "Programa"):
        self._p = programa

    def info(self) -> dict:
        m = self._p.maquina
        return {"modo": m.modo, "servidor": self._p.base(), "loja": m.loja, "tela": m.tela,
                "tela_cheia": m.tela_cheia, "versao": __version__}

    def configurar(self, tela: str, tela_cheia: bool) -> dict:
        m = self._p.maquina
        m.tela = tela if tela in TELAS else ""
        mudou_cheia = bool(tela_cheia) != m.tela_cheia
        m.tela_cheia = bool(tela_cheia)
        self._p.salvar()
        if mudou_cheia and self._p.janela:
            self._p.janela.toggle_fullscreen()
        return {"ok": True}

    def alternar_tela_cheia(self) -> None:
        if self._p.janela:
            self._p.janela.toggle_fullscreen()

    def ir_para_abas(self) -> None:
        """Atalho F2 na tela do painel (que não tem barra de abas)."""
        self._p.carregar(self._p.base() + "/area?tela=painel")

    def conectar(self, endereco: str) -> dict:
        url = descoberta.normalizar(endereco)
        if not url:
            return {"ok": False, "erro": "Digite o IP do computador principal (ex.: 192.168.0.10)."}
        info = descoberta.identificar(url)
        if not info:
            return {"ok": False, "erro": f"O computador principal não respondeu em {url.replace('http://', '')}. "
                                         "Confira o IP (em Administração > Configurações > Conexões, no computador "
                                         "principal), se ele está ligado com o Torres Comandas aberto e se os dois "
                                         "estão na mesma rede."}
        if self._p.maquina.modo == "terminal" and self._p.maquina.id and info["id"] != self._p.maquina.id:
            log.info("Conectando a outro sistema: %s (antes %s)", info["url"], self._p.maquina.servidor)
        self._p.usar_terminal(info)
        return {"ok": True}

    def reconectar(self) -> dict:
        info = self._p.achar_principal()
        if info:
            self._p.usar_terminal(info)
            return {"ok": True}
        return {"ok": False}

    def ser_principal(self) -> dict:
        # Só na primeira vez: um terminal não vira principal pelas telas.
        if self._p.maquina.modo == "terminal":
            return {"ok": False, "erro": "Este computador já está ligado a um computador principal."}
        self._p.usar_principal()
        return {"ok": True}


class Programa:
    def __init__(self, dados: Path, maquina: Maquina, subir_servidor: Callable[[], str],
                 teste: Optional[dict] = None):
        """`subir_servidor()` liga o sistema neste PC e devolve o endereço local."""
        self.dados = dados
        self.maquina = maquina
        self._subir_servidor = subir_servidor
        self.url_local = ""
        self.janela = None
        self.saindo = False
        self.bandeja = None
        self.teste = teste

    # --- estado ---

    def salvar(self) -> None:
        self.maquina.salvar(self.dados)

    def base(self) -> str:
        return self.url_local if self.maquina.modo == "principal" else self.maquina.servidor

    def carregar(self, url: str) -> None:
        if self.janela:
            self.janela.load_url(url)

    def _html_assistente(self, modo: str, mensagem: str = "") -> str:
        html = ASSISTENTE.read_text(encoding="utf-8")
        inicio, fim = html.index("/*ESTADO*/"), html.index("/*FIM*/")
        ip = self.maquina.servidor.replace("http://", "").removesuffix(":8090")
        # "<\/" para um texto vindo da rede (nome da loja) não fechar o <script>
        estado = json.dumps({"modo": modo, "mensagem": mensagem, "ip": ip}, ensure_ascii=False).replace("</", "<\\/")
        return html[:inicio] + estado + html[fim + len("/*FIM*/"):]

    def usar_principal(self) -> None:
        self.maquina.modo = "principal"
        self.maquina.servidor = ""
        self.salvar()
        self._ligar_principal()
        self.carregar(self.url_local + self.maquina.caminho_inicial())

    def usar_terminal(self, info: dict) -> None:
        self.maquina.modo = "terminal"
        self.maquina.servidor = info["url"]
        self.maquina.id = info.get("id", "")
        self.maquina.loja = info.get("loja", "")
        self.salvar()
        log.info("Conectado ao computador principal %s (%s)", info["url"], info.get("loja"))
        self.carregar(info["url"] + self.maquina.caminho_inicial())

    def achar_principal(self) -> Optional[dict]:
        """O principal no IP salvo (None se não responder)."""
        if self.maquina.servidor:
            return descoberta.identificar(self.maquina.servidor)
        return None

    def _ligar_principal(self) -> None:
        if not self.url_local:
            self.url_local = self._subir_servidor()
            info = descoberta.identificar(self.url_local)
            self.maquina.loja = info["loja"] if info else ""
            self._criar_bandeja()

    # --- janela ---

    def url_inicial(self) -> Optional[str]:
        """None = abrir o assistente (primeira vez ou principal não encontrado)."""
        m = self.maquina
        if m.modo == "principal":
            self._ligar_principal()
            return self.url_local + m.caminho_inicial()
        if m.modo == "terminal":
            info = self.achar_principal()
            if info:
                return info["url"] + m.caminho_inicial()
        return None

    def ao_fechar(self):
        # No principal, fechar a janela não desliga o sistema das outras máquinas.
        if self.maquina.modo == "principal" and not self.saindo and self.bandeja is not None:
            threading.Thread(target=self.janela.hide, daemon=True).start()
            if not getattr(self, "_avisou_bandeja", False):
                self._avisou_bandeja = True
                try:
                    self.bandeja.notify("O sistema continua funcionando para as outras máquinas. "
                                        "Para abrir de novo, clique no ícone perto do relógio.", "Torres Comandas")
                except Exception:
                    pass
            return False
        return True

    def mostrar_janela(self) -> None:
        if self.janela:
            self.janela.show()
            self.janela.restore()

    def sair(self) -> None:
        log.info("Encerrando pelo menu da bandeja")
        self.saindo = True
        if self.janela:
            self.janela.destroy()
        if self.bandeja:
            self.bandeja.stop()

    def _criar_bandeja(self) -> None:
        if self.teste:
            return
        try:
            from .bandeja import criar_bandeja
            self.bandeja = criar_bandeja(descoberta.ip_na_rede(), self.url_local.rsplit(":", 1)[-1], self.dados,
                                         self.mostrar_janela, self.sair)
            self.bandeja.run_detached()
        except Exception:
            log.exception("Não foi possível criar o ícone perto do relógio")
            self.bandeja = None

    def rodar(self) -> None:
        ouvir_instancia(self.mostrar_janela)
        url = self.url_inicial()
        modo_assistente = None
        if url is None:
            modo_assistente = "reconectar" if self.maquina.modo == "terminal" else "escolher"

        if not webview2_instalado():
            self._rodar_sem_webview2(url)
            return

        # Som dos alertas (cozinha, garçom, painel) sem precisar tocar na tela antes.
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--autoplay-policy=no-user-gesture-required"
        import webview

        mensagem = ""
        if modo_assistente == "reconectar":
            ip = self.maquina.servidor.replace("http://", "")
            mensagem = (f"O computador principal ({self.maquina.loja + ' — ' if self.maquina.loja else ''}{ip}) "
                        "não respondeu. Confira se ele está ligado e com o Torres Comandas aberto. "
                        "Tentando de novo sozinho a cada 10 segundos...")
        self.janela = webview.create_window(
            "Torres Comandas",
            url=url,
            html=None if url else self._html_assistente(modo_assistente, mensagem),
            js_api=Api(self),
            width=1280, height=800, min_size=(800, 560),
            fullscreen=bool(url) and self.maquina.tela_cheia,
            background_color="#0F172A",
        )
        self.janela.events.closing += self.ao_fechar
        if self.teste:
            threading.Thread(target=self._teste_janela, daemon=True, name="teste").start()
        webview.start(private_mode=False, storage_path=str(self.dados / "janela"))

    def _rodar_sem_webview2(self, url: Optional[str]) -> None:
        log.warning("WebView2 não instalado: abrindo as telas numa janela do Edge")
        if url:
            abrir_no_edge(url, self.maquina.tela_cheia, self.dados / "edge")
        else:
            _mensagem_windows("Torres Comandas",
                              "Falta um componente do Windows (Microsoft Edge WebView2) para mostrar a janela do programa.\n\n"
                              "Instale o Torres Comandas de novo com internet ligada (o instalador baixa o componente) "
                              "ou atualize o Windows.")
            return
        if self.maquina.modo == "principal" and self.bandeja:
            # o sistema continua no ar com o ícone perto do relógio
            threading.Event().wait()

    # --- teste automático da janela (GitHub Actions) ---

    def _teste_janela(self) -> None:
        """Abre a janela, entra (se pedido) e grava o que a tela mostra num arquivo."""
        resultado = {"ok": False}
        try:
            janela = self.janela
            janela.events.loaded.wait(60)

            def js(expr):
                return janela.evaluate_js(expr)

            def esperar(cond, segundos=40):
                fim = time.time() + segundos
                while time.time() < fim:
                    try:
                        if js(cond):
                            return True
                    except Exception:
                        pass
                    time.sleep(0.5)
                return False

            usuario, _, senha = (self.teste.get("login") or "").partition(":")
            if usuario and esperar("location.pathname === '/login'", 20):
                js(f"document.getElementById('usuario').value={json.dumps(usuario)};"
                   f"document.getElementById('senha').value={json.dumps(senha)};document.querySelector('form').submit();")
            esperar("document.readyState === 'complete' && location.pathname !== '/login'", 30)
            if self.teste.get("esperar_abas"):
                esperar("document.querySelectorAll('#abas button').length > 0 && !!document.querySelector('#telas iframe')")
                esperar("(() => { const f = document.querySelector('#telas iframe:not([hidden])');"
                        " return f && f.contentDocument && f.contentDocument.readyState === 'complete'"
                        " && f.contentDocument.title !== ''; })()")
            esperar("!!(window.pywebview && window.pywebview.api)", 20)
            resultado = {
                "ok": True,
                "caminho": js("location.pathname"),
                "titulo": js("document.title"),
                "abas": js("[...document.querySelectorAll('#abas button')].map(b => b.dataset.aba)") or [],
                "aba_ativa": js("(document.querySelector('#abas button.ativa') || {}).dataset?.aba || ''"),
                "tela_na_aba": js("(() => { const f = document.querySelector('#telas iframe:not([hidden])');"
                                  " return f ? f.contentDocument.title : ''; })()"),
                "ponte": js("!!(window.pywebview && window.pywebview.api)"),
                "modo": self.maquina.modo,
                "servidor": self.base(),
            }
        except Exception as exc:  # noqa: BLE001
            resultado = {"ok": False, "erro": repr(exc)}
        Path(self.teste["saida"]).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        self.saindo = True
        self.janela.destroy()


def _mensagem_windows(titulo: str, texto: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texto, titulo, 0x40)
    else:
        log.error("%s: %s", titulo, texto)
