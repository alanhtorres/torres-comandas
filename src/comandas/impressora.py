"""Impressão em impressora térmica ESC/POS (Epson, Elgin, Bematech, Daruma,
Tanca, genéricas chinesas...), de dois jeitos:

- rede: porta TCP "raw" 9100. Não precisa de driver nem de nada instalado
  no PC: os bytes vão direto pro IP da impressora.
- USB: impressora instalada no Windows deste PC (com o driver do fabricante
  ou "Generic / Text Only"). Os bytes vão "crus" (RAW) pelo spooler do
  Windows, sem passar pelo driver gráfico."""
import ctypes
import socket
import sys
import unicodedata
from datetime import datetime

from .banco import moeda, setor_do_item

# Ambientes que recebem os pedidos, cada um com a sua impressora.
SETORES = {"cozinha": "COZINHA", "bar": "BAR"}

ESC = b"\x1b"
GS = b"\x1d"

INICIAR = ESC + b"@"
NEGRITO_ON = ESC + b"E\x01"
NEGRITO_OFF = ESC + b"E\x00"
ALINHAR_ESQ = ESC + b"a\x00"
ALINHAR_CENTRO = ESC + b"a\x01"
# O tamanho vai pelos dois comandos (ESC ! e GS !): cada modelo entende um, e
# assim todas as impressoras imprimem do mesmo jeito.
TAMANHO_NORMAL = ESC + b"!\x00" + GS + b"!\x00"
TAMANHO_DUPLO = ESC + b"!\x30" + GS + b"!\x11"      # dobro da largura e da altura
# Cada impressora guarda a sua fonte/espaçamento padrão (muitas vêm com a
# fonte B, pequena). Isso força o mesmo formato em todas: fonte A, sem
# espaço extra entre letras e espaçamento de linha normal.
FORMATO_PADRAO = ESC + b"M\x00" + ESC + b" \x00" + ESC + b"2" + TAMANHO_NORMAL
CORTAR = GS + b"V\x42\x03"         # avança um pouco e corta (corte parcial)

# Tabela de caracteres (comando ESC t n) de cada codificação suportada.
CODIFICACOES = {
    "cp850": 2,   # Multilíngue — a mais aceita pelas impressoras genéricas
    "cp860": 3,   # Português
    "ascii": None,  # sem acentos: pra impressoras que imprimem lixo nos acentos
}


class ErroImpressora(Exception):
    pass


def _sem_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


class Cupom:
    """Monta os bytes de um cupom linha a linha."""

    def __init__(self, colunas: int = 48, codificacao: str = "cp850"):
        self.colunas = colunas
        self.codificacao = codificacao if codificacao in CODIFICACOES else "cp850"
        self.dados = bytearray(INICIAR + FORMATO_PADRAO)
        tabela = CODIFICACOES[self.codificacao]
        if tabela is not None:
            self.dados += ESC + b"t" + bytes([tabela])

    def _cod(self, texto: str) -> bytes:
        if self.codificacao == "ascii":
            return _sem_acentos(texto).encode("ascii", "replace")
        return texto.encode(self.codificacao, "replace")

    def cmd(self, comando: bytes) -> "Cupom":
        self.dados += comando
        return self

    def linha(self, texto: str = "") -> "Cupom":
        self.dados += self._cod(texto) + b"\n"
        return self

    def separador(self, caractere: str = "-") -> "Cupom":
        return self.linha(caractere * self.colunas)

    def quebrar(self, texto: str, largura: int, recuo: str = "") -> "Cupom":
        """Quebra texto longo em várias linhas sem cortar palavras."""
        palavras = texto.split()
        atual = ""
        for palavra in palavras:
            candidato = (atual + " " + palavra).strip()
            if len(candidato) > largura - len(recuo) and atual:
                self.linha(recuo + atual)
                atual = palavra
            else:
                atual = candidato
        if atual:
            self.linha(recuo + atual)
        return self

    def bytes(self) -> bytes:
        return bytes(self.dados + b"\n\n\n" + CORTAR)


def _hora(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


def cupom_cozinha(pedido: dict, nome_loja: str, colunas: int = 48, codificacao: str = "cp850",
                  setor: str = "cozinha") -> bytes:
    """Cupom de preparo de um ambiente (cozinha ou bar): só os itens dele."""
    c = Cupom(colunas, codificacao)
    c.cmd(ALINHAR_CENTRO).linha(nome_loja).linha(f"PEDIDO {SETORES.get(setor, setor.upper())}")
    c.cmd(TAMANHO_DUPLO + NEGRITO_ON).linha(f"No {pedido['codigo']}").cmd(TAMANHO_NORMAL + NEGRITO_OFF)
    c.cmd(ALINHAR_ESQ)
    origem = {"qrcode": "QR code", "caixa": "Caixa", "garcom": "Garcom"}.get(pedido["origem"], pedido["origem"])
    info = f"Origem: {origem}"
    if pedido["origem"] == "garcom" and pedido.get("usuario_nome"):
        info += f" ({pedido['usuario_nome']})"
    if pedido.get("mesa"):
        info += f"   Mesa: {pedido['mesa']}"
    c.linha(info)
    if pedido.get("cliente"):
        c.linha(f"Cliente: {pedido['cliente']}")
    c.linha(_hora(pedido["criado_em"]))
    c.separador()
    # Itens em fonte dupla: é o que o cozinheiro precisa ler de longe.
    largura_dupla = max(10, colunas // 2)
    # Só o que é deste ambiente (o resto sai na impressora do outro, ou pelo caixa).
    for item in (i for i in pedido["itens"] if setor_do_item(i) == setor):
        c.cmd(TAMANHO_DUPLO + NEGRITO_ON).quebrar(f"{item['quantidade']}x {item['nome']}", largura_dupla)
        c.cmd(TAMANHO_NORMAL + NEGRITO_OFF)
        if item.get("observacao"):
            c.quebrar(f">> {item['observacao']}", colunas, recuo="   ")
    if pedido.get("observacao"):
        c.separador()
        c.cmd(NEGRITO_ON).quebrar(f"OBS: {pedido['observacao']}", colunas).cmd(NEGRITO_OFF)
    c.separador()
    return c.bytes()


def _valor(c: Cupom, rotulo: str, centavos: int, negrito: bool = False) -> None:
    texto = moeda(centavos)
    espacos = max(1, c.colunas - len(rotulo) - len(texto))
    if negrito:
        c.cmd(NEGRITO_ON)
    c.linha(rotulo + " " * espacos + texto)
    if negrito:
        c.cmd(NEGRITO_OFF)


def cupom_conta(titulo: str, pedidos: list, nome_loja: str, taxa_servico_percentual: int = 0,
                colunas: int = 48, codificacao: str = "cp850") -> bytes:
    """Conferência de conta (pré-conta) para o cliente — não é documento fiscal."""
    c = Cupom(colunas, codificacao)
    c.cmd(ALINHAR_CENTRO).linha(nome_loja).cmd(NEGRITO_ON).linha("CONFERENCIA DE CONTA").cmd(NEGRITO_OFF)
    c.linha(titulo).linha(datetime.now().strftime("%d/%m/%Y %H:%M")).cmd(ALINHAR_ESQ).separador()
    subtotal = 0
    for pedido in pedidos:
        for item in pedido["itens"]:
            valor = item["preco_centavos"] * item["quantidade"]
            subtotal += valor
            _valor(c, f"{item['quantidade']}x {item['nome']}"[: c.colunas - 13], valor)
    c.separador()
    _valor(c, "Subtotal", subtotal)
    if taxa_servico_percentual:
        taxa = round(subtotal * taxa_servico_percentual / 100)
        _valor(c, f"Taxa de servico ({taxa_servico_percentual}%) opcional", taxa)
        _valor(c, "Total com taxa", subtotal + taxa, negrito=True)
    else:
        _valor(c, "Total", subtotal, negrito=True)
    c.separador().cmd(ALINHAR_CENTRO).linha("Nao e documento fiscal")
    return c.bytes()


def cupom_fechamento(resumo: dict, nome_loja: str, formas: dict, colunas: int = 48, codificacao: str = "cp850") -> bytes:
    c = Cupom(colunas, codificacao)
    c.cmd(ALINHAR_CENTRO).linha(nome_loja).cmd(NEGRITO_ON).linha("FECHAMENTO DE CAIXA").cmd(NEGRITO_OFF).cmd(ALINHAR_ESQ)
    c.linha(f"Aberto: {_hora(resumo['aberto_em'])} por {resumo['aberto_por_nome']}")
    if resumo.get("fechado_em"):
        c.linha(f"Fechado: {_hora(resumo['fechado_em'])} por {resumo['fechado_por_nome']}")
    c.separador()
    _valor(c, f"Vendas ({resumo['qtd_vendas']})", resumo["total_vendas"], negrito=True)
    for forma, rotulo in formas.items():
        if resumo["por_forma"].get(forma):
            _valor(c, "  " + rotulo, resumo["por_forma"][forma])
    if resumo["descontos"]:
        _valor(c, "Descontos concedidos", resumo["descontos"])
    if resumo["qtd_estornos"]:
        _valor(c, f"Estornos ({resumo['qtd_estornos']})", resumo["total_estornos"])
    c.separador()
    _valor(c, "Fundo de troco (abertura)", resumo["valor_abertura"])
    _valor(c, "+ Vendas em dinheiro", resumo["por_forma"].get("dinheiro", 0))
    _valor(c, "+ Suprimentos", resumo["suprimentos"])
    _valor(c, "- Sangrias", resumo["sangrias"])
    _valor(c, "= Dinheiro esperado", resumo["esperado_dinheiro"] or 0, negrito=True)
    if resumo.get("valor_contado") is not None:
        _valor(c, "Dinheiro contado", resumo["valor_contado"])
        diferenca = resumo["diferenca"] or 0
        rotulo = "Diferenca" if diferenca == 0 else ("SOBRA" if diferenca > 0 else "FALTA")
        _valor(c, rotulo, abs(diferenca), negrito=True)
    if resumo["movimentos"]:
        c.separador()
        for m in resumo["movimentos"]:
            _valor(c, f"{m['tipo'].capitalize()}: {m['motivo']}"[: c.colunas - 13], m["valor"])
    if resumo.get("observacao"):
        c.separador().quebrar(f"Obs: {resumo['observacao']}", c.colunas)
    c.linha().linha().linha("_" * min(30, c.colunas)).linha("Assinatura")
    return c.bytes()


def enviar(host: str, porta: int, dados: bytes, timeout: float = 5.0) -> None:
    if not host:
        raise ErroImpressora("Endereço (IP) da impressora não configurado.")
    try:
        with socket.create_connection((host, int(porta)), timeout=timeout) as sock:
            sock.sendall(dados)
    except OSError as exc:
        raise ErroImpressora(f"Não foi possível imprimir em {host}:{porta} ({exc}).") from exc


# --- Impressora USB (instalada no Windows) --------------------------------------

def _winspool():
    from ctypes import wintypes

    w = ctypes.WinDLL("winspool.drv", use_last_error=True)

    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR), ("pDatatype", wintypes.LPWSTR)]

    w.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    w.OpenPrinterW.restype = wintypes.BOOL
    w.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1)]
    w.StartDocPrinterW.restype = wintypes.DWORD
    for nome in ("StartPagePrinter", "EndPagePrinter", "EndDocPrinter", "ClosePrinter"):
        getattr(w, nome).argtypes = [wintypes.HANDLE]
        getattr(w, nome).restype = wintypes.BOOL
    w.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    w.WritePrinter.restype = wintypes.BOOL
    w.EnumPrintersW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    w.EnumPrintersW.restype = wintypes.BOOL
    return w, DOC_INFO_1


def listar_impressoras_windows() -> list:
    """Nomes das impressoras instaladas neste PC (vazio fora do Windows)."""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes

    class PRINTER_INFO_4(ctypes.Structure):
        _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR), ("Attributes", wintypes.DWORD)]

    w, _ = _winspool()
    flags = 0x2 | 0x4  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    precisa, quantas = wintypes.DWORD(0), wintypes.DWORD(0)
    w.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(precisa), ctypes.byref(quantas))
    if not precisa.value:
        return []
    buf = ctypes.create_string_buffer(precisa.value)
    if not w.EnumPrintersW(flags, None, 4, buf, precisa, ctypes.byref(precisa), ctypes.byref(quantas)):
        return []
    lista = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_4))
    return sorted({lista[i].pPrinterName for i in range(quantas.value) if lista[i].pPrinterName}, key=str.lower)


def enviar_windows(nome: str, dados: bytes) -> None:
    """Manda os bytes ESC/POS "crus" para uma impressora do Windows (USB)."""
    if not nome:
        raise ErroImpressora("Impressora USB não escolhida.")
    if sys.platform != "win32":
        raise ErroImpressora("Impressora USB só funciona com o sistema rodando no Windows.")
    from ctypes import wintypes

    w, DOC_INFO_1 = _winspool()
    handle = wintypes.HANDLE()
    if not w.OpenPrinterW(nome, ctypes.byref(handle), None):
        raise ErroImpressora(f"Impressora \"{nome}\" não encontrada neste PC ({ctypes.FormatError(ctypes.get_last_error())}).")
    try:
        doc = DOC_INFO_1("Torres Comandas", None, "RAW")
        if not w.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
            raise ErroImpressora(f"Não foi possível imprimir em \"{nome}\" ({ctypes.FormatError(ctypes.get_last_error())}).")
        try:
            w.StartPagePrinter(handle)
            escritos = wintypes.DWORD(0)
            ok = w.WritePrinter(handle, dados, len(dados), ctypes.byref(escritos))
            w.EndPagePrinter(handle)
        finally:
            w.EndDocPrinter(handle)
        if not ok or escritos.value != len(dados):
            raise ErroImpressora(f"Não foi possível imprimir em \"{nome}\" ({ctypes.FormatError(ctypes.get_last_error())}).")
    finally:
        w.ClosePrinter(handle)


def enviar_para(cfg: dict, qual: str, dados: bytes) -> None:
    """Imprime na impressora `qual` (cozinha, bar ou caixa) do jeito configurado."""
    if cfg.get(f"impressora_{qual}_tipo") == "usb":
        enviar_windows(cfg.get(f"impressora_{qual}_usb", ""), dados)
    else:
        enviar(cfg[f"impressora_{qual}_host"], cfg[f"impressora_{qual}_porta"], dados)
