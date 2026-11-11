"""Testa o app do garçom num Android emulado (GitHub Actions), contra o
sistema rodando de verdade no mesmo computador (o emulador enxerga o PC em
10.0.2.2). Usa o adb para mexer no aparelho e o DevTools do WebView para ler
e tocar na página. Salva fotos da tela em PASTA_FOTOS para conferência.

Uso: python build_tools/testar_app_android.py <app.apk> <pasta_fotos>
"""
import http.cookiejar
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import websocket  # pip install websocket-client

APK, FOTOS = sys.argv[1], Path(sys.argv[2])
FOTOS.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8090"
PACOTE = "br.com.torres.garcom"


def adb(*args, check=True):
    r = subprocess.run(["adb", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)}: {r.stderr or r.stdout}")
    return r.stdout


def foto(nome):
    with open(FOTOS / f"{nome}.png", "wb") as f:
        f.write(subprocess.run(["adb", "exec-out", "screencap", "-p"], capture_output=True).stdout)


def esperar(descricao, condicao, segundos=30):
    fim = time.time() + segundos
    ultimo = None
    while time.time() < fim:
        try:
            ultimo = condicao()
            if ultimo:
                return ultimo
        except Exception as exc:  # noqa: BLE001 — repete até o prazo
            ultimo = exc
        time.sleep(1)
    foto("falha-" + re.sub(r"\W+", "-", descricao)[:40])
    raise AssertionError(f"Não aconteceu: {descricao} (último: {ultimo!r})")


def passo(texto):
    print(f"\n==> {texto}", flush=True)


# --- Sistema: administrador, produto, mesa e garçom --------------------------

class Api:
    def __init__(self):
        self.abrir = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())).open

    def form(self, caminho, dados):
        return self.abrir(urllib.request.Request(BASE + caminho, data=urllib.parse.urlencode(dados).encode()))

    def json(self, metodo, caminho, corpo=None):
        req = urllib.request.Request(BASE + caminho, method=metodo, headers={"Content-Type": "application/json"},
                                     data=None if corpo is None else json.dumps(corpo).encode())
        return json.loads(self.abrir(req).read() or b"{}")


passo("Preparando o sistema")
admin = Api()
admin.form("/primeiro-acesso", {"nome": "Ana", "usuario": "ana", "senha": "1234ab", "confirmar": "1234ab"})
produto = admin.json("POST", "/api/produtos", {"nome": "X-Burger", "preco_centavos": 2500, "categoria": "Lanches"})["produto"]
admin.json("POST", "/api/mesas", {"numero": "5"})
token = admin.json("GET", "/api/mesas")["mesas"][0]["token"]
admin.json("POST", "/api/usuarios", {"nome": "Bruno", "login": "bruno", "senha": "1234ab", "permissoes": ["garcom"]})
ident = admin.json("GET", "/api/identificar")
assert ident["app"] and ident["app"]["versao_codigo"] > 0, ident
print("sistema:", ident)

# --- App ---------------------------------------------------------------------

passo("Instalando o app")
adb("install", "-r", APK)
adb("shell", "pm", "grant", PACOTE, "android.permission.POST_NOTIFICATIONS", check=False)

passo("Abrindo pelo link do QR code (página /app)")
adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
    "-d", "torrescomandas://conectar?servidor=http%3A%2F%2F10.0.2.2%3A8090")


class Pagina:
    """Fala com a página do WebView pelo DevTools (Runtime.evaluate)."""

    def __init__(self):
        self.ws = None
        self.n = 0

    def conectar(self):
        unix = adb("shell", "cat", "/proc/net/unix")
        sockets = sorted(set(re.findall(r"@(webview_devtools_remote_\d+)", unix)))
        assert sockets, "WebView sem DevTools"
        adb("forward", "tcp:9222", "localabstract:" + sockets[-1])
        alvos = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json").read())
        alvo = next(a for a in alvos if a.get("type") == "page" and "8090" in a.get("url", ""))
        self.ws = websocket.create_connection(alvo["webSocketDebuggerUrl"], suppress_origin=True, timeout=20)
        return True

    def js(self, expressao):
        for tentativa in range(2):
            try:
                if not self.ws:
                    self.conectar()
                self.n += 1
                self.ws.send(json.dumps({"id": self.n, "method": "Runtime.evaluate", "params": {
                    "expression": expressao, "awaitPromise": True, "returnByValue": True}}))
                while True:
                    r = json.loads(self.ws.recv())
                    if r.get("id") == self.n:
                        res = r.get("result", {})
                        if "exceptionDetails" in res:
                            raise RuntimeError(res["exceptionDetails"])
                        return res.get("result", {}).get("value")
            except (websocket.WebSocketException, OSError, StopIteration, AssertionError):
                self.ws = None
                if tentativa:
                    raise
                time.sleep(1)


pagina = Pagina()


def login_na_frente():
    # Logo depois de ligar, o emulador às vezes põe a tela inicial do Android
    # por cima do app: traz o app de volta para a frente e tenta de novo.
    if f"{PACOTE}/" not in adb("shell", "dumpsys", "activity", "activities").split("ResumedActivity")[1][:300]:
        adb("shell", "am", "start", "-n", f"{PACOTE}/.MainActivity", check=False)
    return (pagina.js("location.pathname") or "") == "/login"


try:
    esperar("página de login no app", login_na_frente, 90)
except AssertionError:
    (FOTOS / "logcat.txt").write_text(adb("logcat", "-d", "-t", "800", check=False), encoding="utf-8")
    raise
foto("1-login")

passo("Entrando como garçom")
pagina.js("document.getElementById('usuario').value='bruno'; document.getElementById('senha').value='1234ab';"
          "document.querySelector('form').submit(); true")
esperar("tela do garçom", lambda: pagina.js("location.pathname") == "/garcom" and pagina.js("!!document.querySelector('#mesas button')"), 30)
assert pagina.js("typeof window.TorresApp === 'object'"), "ponte com o app não existe"
assert pagina.js("[...document.querySelectorAll('.topo nav a')].some(a => a.textContent.includes('App'))"), "sem o botão ⚙️ App"
foto("2-garcom")

passo("Pedido em anotação sobrevive a recarregar a página")
pagina.js("[...document.querySelectorAll('#mesas button')].find(b => b.textContent === '5').click();"
          "document.querySelector('#produtos .qtd button.mais').click(); true")
pagina.js("location.reload(); true")
time.sleep(3)
esperar("rascunho restaurado", lambda: "Mesa 5" in (pagina.js("document.getElementById('barra-pedido').textContent") or "")
        and "1 item" in pagina.js("document.getElementById('barra-pedido').textContent"), 20)
foto("3-rascunho")

passo("Notificação com o app em segundo plano (mesa chama pelo QR code)")
pagina.js("window.__marcador = 'sem-recarregar'; true")
adb("shell", "input", "keyevent", "KEYCODE_HOME")
time.sleep(3)
cliente = Api()
cliente.json("POST", f"/api/cliente/{token}/chamar", {"tipo": "garcom"})
esperar("notificação do chamado", lambda: "Mesa 5 está chamando" in adb("shell", "dumpsys", "notification", "--noredact"), 30)
assert "turno ativo" in adb("shell", "dumpsys", "notification", "--noredact"), "sem o aviso fixo do turno"
adb("shell", "cmd", "statusbar", "expand-notifications")
time.sleep(2)
foto("4-notificacao")


def tocar_texto(trecho):
    """Toca no elemento da tela (fora do WebView) que contém o texto."""
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    xml = adb("shell", "cat", "/sdcard/ui.xml")
    for no in re.finditer(r'<node [^>]*?text="([^"]*)"[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        if trecho.lower() in no.group(1).lower():
            x1, y1, x2, y2 = map(int, no.group(2, 3, 4, 5))
            adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
            return True
    return False


def tocar_notificacao(trecho):
    """Abre a gaveta de notificações (de novo a cada tentativa) e toca no texto."""
    adb("shell", "cmd", "statusbar", "expand-notifications")
    time.sleep(2)
    return tocar_texto(trecho)


passo("Botão '✓ Atendi' da notificação marca o chamado no sistema")
esperar("botão Atendi na notificação", lambda: tocar_notificacao("Atendi"), 20)
esperar("chamado atendido no sistema", lambda: admin.json("GET", "/api/estado")["chamados_garcom"] == [], 20)
adb("shell", "cmd", "statusbar", "collapse")

passo("Pedido pronto avisa e o toque abre a aba Entregar")
pedido = admin.json("POST", "/api/pedidos", {"itens": [{"produto_id": produto["id"], "quantidade": 1}], "mesa": "5"})["pedido"]
for status in ("preparando", "pronto"):
    try:
        admin.json("POST", f"/api/pedidos/{pedido['id']}/status", {"status": status})
    except urllib.error.HTTPError:
        pass
esperar("notificação do pedido pronto", lambda: f"Pedido {pedido['codigo']} pronto" in adb("shell", "dumpsys", "notification", "--noredact"), 30)
adb("shell", "cmd", "statusbar", "expand-notifications")
time.sleep(2)
foto("5-pronto")
esperar("tocar na notificação do pedido", lambda: tocar_notificacao(f"Pedido {pedido['codigo']} pronto"), 20)
esperar("app aberto na aba Entregar", lambda: pagina.js("location.hash") == "#entregar"
        and pagina.js("!document.getElementById('aba-entregar').hidden"), 20)
assert pagina.js("window.__marcador") == "sem-recarregar", "a página recarregou ao voltar para o app"
foto("6-entregar")

passo("Botão voltar não fecha o app (só manda para segundo plano)")
adb("shell", "input", "keyevent", "KEYCODE_BACK")
time.sleep(2)
adb("shell", "input", "keyevent", "KEYCODE_BACK")
time.sleep(2)
assert adb("shell", "pidof", PACOTE, check=False).strip(), "o app foi fechado"
adb("shell", "am", "start", "-n", f"{PACOTE}/.MainActivity")
time.sleep(3)
assert pagina.js("window.__marcador") == "sem-recarregar", "a página recarregou ao reabrir o app"
assert pagina.js("location.pathname") == "/garcom"

def texto_na_tela(trecho):
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    return trecho.lower() in adb("shell", "cat", "/sdcard/ui.xml").lower()


def digitar_ip(ip):
    """Apaga o campo do IP e digita outro."""
    esperar("campo do IP", lambda: tocar_texto("10.0.2") or tocar_texto("192.168"), 10)
    adb("shell", "input", "keyevent", "KEYCODE_MOVE_END")
    for _ in range(25):
        adb("shell", "input", "keyevent", "KEYCODE_DEL")
    adb("shell", "input", "text", ip)


passo("Trocar o IP: IP errado explica o problema; IP certo conecta")
adb("shell", "am", "start", "-n", f"{PACOTE}/.ConectarActivity")
time.sleep(2)
assert texto_na_tela("IP do computador principal"), "tela de conexão sem o campo do IP"
assert not texto_na_tela("Procurar"), "a tela de conexão ainda tem a busca na rede"
assert texto_na_tela("10.0.2.2"), "o IP salvo não veio preenchido"
digitar_ip("10.0.2.77")
esperar("botão Conectar", lambda: tocar_texto("Conectar"), 10)
esperar("explicação do IP que não respondeu", lambda: texto_na_tela("respondeu no IP 10.0.2.77"), 30)
foto("7-ip-errado")
digitar_ip("10.0.2.2")
esperar("botão Conectar", lambda: tocar_texto("Conectar"), 10)
esperar("conectou e voltou para a tela do garçom",
        lambda: f"{PACOTE}/.MainActivity" in adb("shell", "dumpsys", "activity", "activities").split("ResumedActivity")[1][:300], 60)
esperar("página do garçom de novo", lambda: pagina.js("location.pathname") == "/garcom", 30)
foto("8-reconectado")

print("\nOK: app do garçom testado de ponta a ponta no Android")
