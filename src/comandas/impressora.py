"""Impressão em impressora térmica de rede (ESC/POS, porta TCP "raw" 9100 —
o padrão de praticamente todas as impressoras de cupom/cozinha com rede:
Epson, Elgin, Bematech, Daruma, Tanca, genéricas chinesas...).

Não precisa de driver nem de nada instalado no PC: os bytes vão direto pro
IP da impressora."""
import socket
import unicodedata
from datetime import datetime

from .banco import moeda

ESC = b"\x1b"
GS = b"\x1d"

INICIAR = ESC + b"@"
NEGRITO_ON = ESC + b"E\x01"
NEGRITO_OFF = ESC + b"E\x00"
ALINHAR_ESQ = ESC + b"a\x00"
ALINHAR_CENTRO = ESC + b"a\x01"
TAMANHO_NORMAL = GS + b"!\x00"
TAMANHO_DUPLO = GS + b"!\x11"      # dobro da largura e da altura
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
        self.dados = bytearray(INICIAR)
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


def cupom_cozinha(pedido: dict, nome_loja: str, colunas: int = 48, codificacao: str = "cp850") -> bytes:
    c = Cupom(colunas, codificacao)
    c.cmd(ALINHAR_CENTRO).linha(nome_loja).linha("PEDIDO COZINHA")
    c.cmd(TAMANHO_DUPLO + NEGRITO_ON).linha(f"No {pedido['codigo']}").cmd(TAMANHO_NORMAL + NEGRITO_OFF)
    c.cmd(ALINHAR_ESQ)
    origem = {"qrcode": "QR code", "caixa": "Caixa"}.get(pedido["origem"], pedido["origem"])
    info = f"Origem: {origem}"
    if pedido.get("mesa"):
        info += f"   Mesa: {pedido['mesa']}"
    c.linha(info)
    if pedido.get("cliente"):
        c.linha(f"Cliente: {pedido['cliente']}")
    c.linha(_hora(pedido["criado_em"]))
    c.separador()
    # Itens em fonte dupla: é o que o cozinheiro precisa ler de longe.
    largura_dupla = max(10, colunas // 2)
    for item in pedido["itens"]:
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
