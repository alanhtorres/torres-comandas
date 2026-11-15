"""Relatório para download: o administrador escolhe o período, as seções
e o formato (planilha Excel .xlsx ou PDF). Tudo é gerado no próprio PC,
sem internet.

Cada seção vira uma tabela com colunas tipadas (texto, dinheiro, número,
data) — a planilha guarda números e datas de verdade (dá para somar e
filtrar no Excel) e o PDF mostra tudo formatado."""
import io
from datetime import datetime
from xml.sax.saxutils import escape

from .banco import FORMAS_PAGAMENTO, Banco, ErroNegocio, moeda

# chave: (título, permissão extra exigida além de "relatorios")
SECOES = {
    "resumo": ("Resumo do período", None),
    "formas": ("Vendas por forma de pagamento", None),
    "dias": ("Vendas por dia", None),
    "produtos": ("Produtos vendidos", None),
    "atendentes": ("Vendas por atendente", None),
    "vendas": ("Todas as vendas (pagamento por pagamento)", None),
    "caixas": ("Abertura e fechamento de caixa", None),
    "movimentos": ("Sangrias e suprimentos", None),
    "estornos": ("Pagamentos estornados", None),
    "cancelamentos": ("Pedidos e itens cancelados", None),
    "comandas": ("Comandas do período", None),
    "historico": ("Histórico de ações dos usuários", "historico"),
    "clientes": ("Cadastro de clientes", "clientes"),
}
FORMATOS = ("xlsx", "pdf")

# Nome curto de cada aba da planilha (o Excel aceita no máximo 31 caracteres).
ABAS = {"resumo": "Resumo", "formas": "Formas de pagamento", "dias": "Vendas por dia", "produtos": "Produtos",
        "atendentes": "Atendentes", "vendas": "Vendas", "caixas": "Caixas", "movimentos": "Sangrias e suprimentos",
        "estornos": "Estornos", "cancelamentos": "Cancelamentos", "comandas": "Comandas", "historico": "Histórico",
        "clientes": "Clientes"}

# tipos de coluna
TEXTO, DINHEIRO, NUMERO, DATAHORA, DATA = "texto", "dinheiro", "numero", "datahora", "data"


def _ts(ts):
    return datetime.fromtimestamp(ts) if ts else None


def _dia(iso):
    return datetime.strptime(iso, "%Y-%m-%d") if iso else None


def montar(banco: Banco, de: str, ate: str, secoes: list) -> list:
    """Lista de seções: {"titulo", "colunas": [(nome, tipo)], "linhas", "total": bool}."""
    secoes = [s for s in SECOES if s in secoes]
    if not secoes:
        raise ErroNegocio("Escolha pelo menos uma informação para o relatório.")
    r = banco.relatorio(de, ate)
    saida = []

    def secao(chave, colunas, linhas, total=False):
        saida.append({"chave": chave, "titulo": SECOES[chave][0], "colunas": colunas, "linhas": linhas, "total": total})

    for chave in secoes:
        if chave == "resumo":
            canc = r["cancelados"]
            secao(chave, [("Informação", TEXTO), ("Valor", DINHEIRO), ("Quantidade", NUMERO)], [
                ["Total vendido (líquido)", r["total_vendas"], r["qtd_vendas"]],
                ["Total bruto (antes de descontos)", r["total_bruto"], None],
                ["Descontos concedidos", r["descontos"], None],
                ["Acréscimos / taxa de serviço", r["acrescimos"], None],
                ["Ticket médio", r["ticket_medio"], None],
                ["Pagamentos estornados", sum(e["total"] for e in r["estornos"]), len(r["estornos"])],
                ["Pedidos cancelados", sum(c["total_centavos"] for c in canc), len(canc)],
                ["A receber agora (pedidos sem pagamento)", r["a_receber"]["total"], r["a_receber"]["quantidade"]],
            ])
        elif chave == "formas":
            secao(chave, [("Forma de pagamento", TEXTO), ("Valor", DINHEIRO)],
                  [[nome, r["por_forma"][f]] for f, nome in FORMAS_PAGAMENTO.items() if r["por_forma"][f]], total=True)
        elif chave == "dias":
            secao(chave, [("Dia", DATA), ("Valor vendido", DINHEIRO)],
                  [[_dia(d["dia"]), d["valor"]] for d in r["por_dia"]], total=True)
        elif chave == "produtos":
            secao(chave, [("Produto", TEXTO), ("Quantidade", NUMERO), ("Valor (sem descontos)", DINHEIRO)],
                  [[p["nome"], p["quantidade"], p["valor"]] for p in r["por_produto"]], total=True)
        elif chave == "atendentes":
            secao(chave, [("Atendente (quem recebeu)", TEXTO), ("Vendas", NUMERO), ("Valor", DINHEIRO)],
                  [[u["nome"], u["quantidade"], u["valor"]] for u in r["por_usuario"]], total=True)
        elif chave == "vendas":
            linhas = []
            for rec in banco.recebimentos_periodo(de, ate):
                formas = {f["forma"]: f["valor"] for f in rec["formas"]}
                linhas.append([_ts(rec["criado_em"]), rec["descricao"], rec["usuario_nome"], rec["subtotal"], rec["desconto"],
                               rec["acrescimo"], rec["total"], *(formas.get(f, 0) for f in FORMAS_PAGAMENTO), rec["troco"],
                               f"ESTORNADO: {rec['motivo_estorno']}" if rec["estornado_em"] else "OK"])
            secao(chave, [("Data/hora", DATAHORA), ("Descrição", TEXTO), ("Atendente", TEXTO), ("Subtotal", DINHEIRO),
                          ("Desconto", DINHEIRO), ("Acréscimo", DINHEIRO), ("Total", DINHEIRO),
                          *((nome, DINHEIRO) for nome in FORMAS_PAGAMENTO.values()), ("Troco", DINHEIRO), ("Situação", TEXTO)],
                  linhas)
        elif chave == "caixas":
            secao(chave, [("Abertura", DATAHORA), ("Aberto por", TEXTO), ("Fundo de troco", DINHEIRO), ("Fechamento", DATAHORA),
                          ("Fechado por", TEXTO), ("Vendas", NUMERO), ("Total vendido", DINHEIRO), ("Sangrias", DINHEIRO),
                          ("Suprimentos", DINHEIRO), ("Dinheiro esperado", DINHEIRO), ("Dinheiro contado", DINHEIRO),
                          ("Diferença (+sobra / -falta)", DINHEIRO), ("Observação", TEXTO)],
                  [[_ts(s["aberto_em"]), s["aberto_por_nome"], s["valor_abertura"], _ts(s["fechado_em"]),
                    s["fechado_por_nome"] or "(aberto)", s["qtd_vendas"], s["total_vendas"], s["sangrias"], s["suprimentos"],
                    s["esperado_dinheiro"], s["valor_contado"], s["diferenca"], s["observacao"]] for s in r["sessoes"]])
        elif chave == "movimentos":
            linhas = [[_ts(m["criado_em"]), "Sangria (retirada)" if m["tipo"] == "sangria" else "Suprimento (reforço)",
                       m["valor"] if m["tipo"] == "suprimento" else -m["valor"], m["motivo"], m["usuario_nome"]]
                      for s in r["sessoes"] for m in s["movimentos"]]
            secao(chave, [("Data/hora", DATAHORA), ("Tipo", TEXTO), ("Valor", DINHEIRO), ("Motivo", TEXTO), ("Usuário", TEXTO)],
                  linhas, total=True)
        elif chave == "estornos":
            secao(chave, [("Estornado em", DATAHORA), ("Venda", TEXTO), ("Valor", DINHEIRO), ("Recebido por", TEXTO),
                          ("Estornado por", TEXTO), ("Motivo", TEXTO)],
                  [[_ts(e["estornado_em"]), e["descricao"], e["total"], e["usuario_nome"], e["estornado_por_nome"],
                    e["motivo_estorno"]] for e in r["estornos"]], total=True)
        elif chave == "cancelamentos":
            secao(chave, [("Cancelado em", DATAHORA), ("Pedido", TEXTO), ("Mesa", TEXTO), ("Valor", DINHEIRO),
                          ("Cancelado por", TEXTO), ("Motivo", TEXTO)],
                  [[_ts(c["atualizado_em"]), "Nº " + c["codigo"], c["mesa"], c["total_centavos"], c["cancelado_por_nome"],
                    c["motivo_cancelamento"]] for c in r["cancelados"]], total=True)
        elif chave == "comandas":
            secao(chave, [("Comanda", TEXTO), ("Cliente", TEXTO), ("Telefone", TEXTO), ("Aberta em", DATAHORA),
                          ("Aberta por", TEXTO), ("Fechada em", DATAHORA), ("Situação", TEXTO), ("Consumo", DINHEIRO),
                          ("A receber", DINHEIRO)],
                  [[k["numero"], k["cliente_nome"], k["telefone_formatado"], _ts(k["aberta_em"]), k["aberta_por_nome"],
                    _ts(k["fechada_em"]), "aberta" if k["aberta"] else (k["motivo_fechamento"] or "fechada"), k["total"],
                    k["a_receber"]] for k in banco.comandas_periodo(de, ate)], total=True)
        elif chave == "historico":
            secao(chave, [("Data/hora", DATAHORA), ("Usuário", TEXTO), ("Ação", TEXTO), ("Detalhes", TEXTO)],
                  [[_ts(a["criado_em"]), a["usuario_nome"], a["acao"], a["detalhes"]]
                   for a in reversed(banco.listar_auditoria(de, ate, limite=5000))])
        elif chave == "clientes":
            secao(chave, [("Nome", TEXTO), ("Telefone", TEXTO), ("CPF", TEXTO), ("Nascimento", DATA),
                          ("Aceita mensagens", TEXTO), ("Visitas", NUMERO), ("Última visita", DATAHORA), ("Total gasto", DINHEIRO),
                          ("Cadastrado em", DATAHORA)],
                  [[c["nome"], c["telefone_formatado"], c["cpf_formatado"], _dia(c["nascimento"]),
                    "Sim" if c["aceita_mensagens"] else "Não", c["visitas"], _ts(c["ultima_visita"]), c["total_gasto"],
                    _ts(c["criado_em"])] for c in banco.listar_clientes()], total=True)
    return saida


def _texto_celula(valor, tipo) -> str:
    if valor is None or valor == "":
        return ""
    if tipo == DINHEIRO:
        return moeda(valor)
    if tipo == DATAHORA:
        return valor.strftime("%d/%m/%Y %H:%M")
    if tipo == DATA:
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def _totais(sec):
    return [sum(l[i] or 0 for l in sec["linhas"]) if tipo in (DINHEIRO, NUMERO) and i > 0 else None
            for i, (_, tipo) in enumerate(sec["colunas"])]


# --- Excel -------------------------------------------------------------------

def gerar_xlsx(secoes: list, cabecalho: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    capa = wb.active
    capa.title = "Relatório"
    titulo = Font(bold=True, size=16)
    capa["A1"] = f"Relatório — {cabecalho['loja']}"
    capa["A1"].font = titulo
    for i, (rotulo, valor) in enumerate((("Período", cabecalho["periodo"]), ("Gerado em", cabecalho["gerado_em"]),
                                         ("Gerado por", cabecalho["gerado_por"])), start=3):
        capa.cell(i, 1, rotulo).font = Font(bold=True)
        capa.cell(i, 2, valor)
    capa.cell(7, 1, "Conteúdo (uma aba para cada):").font = Font(bold=True)
    for i, sec in enumerate(secoes, start=8):
        capa.cell(i, 1, "• " + sec["titulo"])
    capa.column_dimensions["A"].width = 34
    capa.column_dimensions["B"].width = 40

    preenchimento = PatternFill("solid", fgColor="1E293B")
    fonte_cab = Font(bold=True, color="FFFFFF")
    formatos = {DINHEIRO: '"R$" #,##0.00;[Red]-"R$" #,##0.00', NUMERO: "0", DATAHORA: "dd/mm/yyyy hh:mm", DATA: "dd/mm/yyyy"}
    usados = set()
    for sec in secoes:
        nome = ABAS.get(sec["chave"]) or "".join(ch for ch in sec["titulo"] if ch not in '[]:*?/\\')[:31]
        while nome in usados:
            nome = nome[:28] + f" {len(usados)}"
        usados.add(nome)
        ws = wb.create_sheet(nome)
        for col, (rotulo, _) in enumerate(sec["colunas"], start=1):
            c = ws.cell(1, col, rotulo)
            c.font, c.fill = fonte_cab, preenchimento
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for lin, linha in enumerate(sec["linhas"], start=2):
            for col, (valor, (_, tipo)) in enumerate(zip(linha, sec["colunas"]), start=1):
                if tipo == DINHEIRO and valor is not None:
                    valor = valor / 100
                c = ws.cell(lin, col, valor)
                if tipo in formatos:
                    c.number_format = formatos[tipo]
        if sec["total"] and sec["linhas"]:
            lin = len(sec["linhas"]) + 2
            ws.cell(lin, 1, "TOTAL").font = Font(bold=True)
            for col, total in enumerate(_totais(sec), start=1):
                if total is not None and col > 1:
                    tipo = sec["colunas"][col - 1][1]
                    c = ws.cell(lin, col, total / 100 if tipo == DINHEIRO else total)
                    c.font, c.number_format = Font(bold=True), formatos[tipo]
        if not sec["linhas"]:
            ws.cell(2, 1, "Nada no período.")
        ws.freeze_panes = "A2"
        if sec["linhas"]:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(sec['colunas']))}{len(sec['linhas']) + 1}"
        for col, (rotulo, tipo) in enumerate(sec["colunas"], start=1):
            maior = max([len(rotulo)] + [len(_texto_celula(l[col - 1], tipo)) for l in sec["linhas"]])
            ws.column_dimensions[get_column_letter(col)].width = min(60, max(10, maior + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- PDF -------------------------------------------------------------------

def _pdf_seguro(texto: str) -> str:
    """As fontes padrão do PDF cobrem o português (cp1252), mas não emojis ou
    setas; troca a seta e descarta o que não dá para desenhar."""
    texto = str(texto).replace("→", "->").replace("—", "-")
    return texto.encode("cp1252", "ignore").decode("cp1252")


def gerar_pdf(secoes: list, cabecalho: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    pagina = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=pagina, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=14 * mm, title=f"Relatório — {cabecalho['loja']}", author="Torres Comandas")
    estilos = getSampleStyleSheet()
    celula = ParagraphStyle("celula", parent=estilos["BodyText"], fontSize=7.5, leading=9)
    celula_dir = ParagraphStyle("celula_dir", parent=celula, alignment=2)
    cab = ParagraphStyle("cab", parent=celula, textColor=colors.white, fontName="Helvetica-Bold")
    cab_dir = ParagraphStyle("cab_dir", parent=cab, alignment=2)
    p = lambda t, e=celula: Paragraph(escape(_pdf_seguro(t)), e)

    historia = [
        Paragraph(escape(_pdf_seguro(f"Relatório — {cabecalho['loja']}")), estilos["Title"]),
        Paragraph(escape(_pdf_seguro(f"Período: {cabecalho['periodo']} · Gerado em {cabecalho['gerado_em']} por {cabecalho['gerado_por']}")),
                  estilos["Normal"]),
        Spacer(1, 6 * mm),
    ]
    largura = pagina[0] - 24 * mm
    for sec in secoes:
        historia.append(Paragraph(escape(_pdf_seguro(sec["titulo"])), estilos["Heading2"]))
        if not sec["linhas"]:
            historia += [Paragraph("Nada no período.", estilos["Normal"]), Spacer(1, 4 * mm)]
            continue
        tipos = [t for _, t in sec["colunas"]]
        dados = [[p(nome, cab) for nome, _ in sec["colunas"]]]
        for linha in sec["linhas"]:
            dados.append([p(_texto_celula(v, t), celula_dir if t in (DINHEIRO, NUMERO) else celula) for v, t in zip(linha, tipos)])
        if sec["total"]:
            totais = _totais(sec)
            # Linha de total em fundo escuro: texto branco para dar leitura.
            dados.append([p("TOTAL", cab)] + [p(_texto_celula(t, tipo), cab_dir) if t is not None else ""
                                               for t, tipo in zip(totais[1:], tipos[1:])])
        # Colunas de texto longo (detalhes, descrição, motivo) ganham mais espaço.
        pesos = [3 if nome in ("Detalhes", "Descrição", "Motivo", "Observação", "Venda", "Informação") else
                 1.6 if t in (TEXTO, DATAHORA) else 1 for nome, t in sec["colunas"]]
        larguras = [largura * w / sum(pesos) for w in pesos]
        tabela = Table(dados, colWidths=larguras, repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        if sec["total"]:
            estilo.append(("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#334155")))
        tabela.setStyle(TableStyle(estilo))
        historia += [tabela, Spacer(1, 6 * mm)]

    def rodape(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(12 * mm, 7 * mm, _pdf_seguro(f"Torres Comandas - {cabecalho['loja']} - {cabecalho['periodo']}"))
        canvas.drawRightString(pagina[0] - 12 * mm, 7 * mm, f"Página {documento.page}")
        canvas.restoreState()

    doc.build(historia, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()


def exportar(banco: Banco, de: str, ate: str, secoes: list, formato: str, gerado_por: str) -> tuple:
    """(bytes, nome do arquivo, tipo MIME)."""
    if formato not in FORMATOS:
        raise ErroNegocio("Formato inválido.")
    dados = montar(banco, de, ate, secoes)
    fmt = lambda iso: datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    cabecalho = {
        "loja": banco.config()["nome_loja"],
        "periodo": fmt(de) if de == ate else f"{fmt(de)} a {fmt(ate)}",
        "gerado_em": datetime.fromtimestamp(banco.agora()).strftime("%d/%m/%Y %H:%M"),
        "gerado_por": gerado_por,
    }
    nome = f"relatorio_{de}_a_{ate}.{formato}"
    if formato == "xlsx":
        return gerar_xlsx(dados, cabecalho), nome, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return gerar_pdf(dados, cabecalho), nome, "application/pdf"
