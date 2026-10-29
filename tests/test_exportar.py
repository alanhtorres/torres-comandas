import io
from datetime import datetime

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from comandas import exportar
from comandas.banco import Banco, ErroNegocio


@pytest.fixture
def banco_com_movimento(tmp_path):
    banco = Banco(tmp_path / "t.db")
    banco.salvar_config({"nome_loja": "Lanchonete São João", "modo_comandas_ativo": True})
    ana = banco.criar_primeiro_admin({"nome": "Ana", "login": "ana", "senha": "1234"})
    ana = {"id": ana["id"], "nome": "Ana"}
    burger = banco.criar_produto({"nome": "X-Burger", "preco_centavos": 2500})
    suco = banco.criar_produto({"nome": "Suco de maçã", "preco_centavos": 900})
    maria = banco.criar_cliente({"nome": "Maria Conceição", "telefone": "11987654321", "cpf": "52998224725",
                                 "aceita_mensagens": True}, por=ana)
    banco.abrir_caixa(10000, ana)
    k = banco.abrir_comanda(maria["id"], por=ana)
    p1 = banco.criar_pedido([{"produto_id": burger["id"], "quantidade": 2}], comanda_id=k["id"], por=ana)
    banco.receber([p1["id"]], [{"forma": "pix", "valor": 3000}, {"forma": "dinheiro", "valor": 3000}], ana, desconto=1000)
    p2 = banco.criar_pedido([{"produto_id": suco["id"]}], por=ana)
    banco.mudar_status(p2["id"], "cancelado", por=ana, motivo="cliente desistiu")
    banco.movimentar_caixa("sangria", 2000, "compra de gelo", ana)
    banco.fechar_caixa(9500, "falta de troco", ana)
    hoje = datetime.now().strftime("%Y-%m-%d")
    return banco, hoje


def test_monta_todas_as_secoes(banco_com_movimento):
    banco, hoje = banco_com_movimento
    secoes = exportar.montar(banco, hoje, hoje, list(exportar.SECOES))
    por_chave = {s["chave"]: s for s in secoes}
    assert list(por_chave) == list(exportar.SECOES)
    assert por_chave["resumo"]["linhas"][0][1:] == [4000, 1]          # vendeu 50 - 10 de desconto
    assert por_chave["formas"]["linhas"] == [["Dinheiro", 1000], ["Pix", 3000]]
    assert por_chave["produtos"]["linhas"] == [["X-Burger", 2, 5000]]
    caixa = por_chave["caixas"]["linhas"][0]
    assert caixa[9] == 9000 and caixa[10] == 9500 and caixa[11] == 500       # 100 + 10 - 20 = 90; contou 95
    assert por_chave["movimentos"]["linhas"][0][2] == -2000
    assert por_chave["cancelamentos"]["linhas"][0][5] == "cliente desistiu"
    assert por_chave["comandas"]["linhas"][0][:2] == ["1", "Maria Conceição"]
    assert por_chave["clientes"]["linhas"][0][2] == "529.982.247-25"
    assert any(l[2] == "Fechou o caixa" for l in por_chave["historico"]["linhas"])
    with pytest.raises(ErroNegocio, match="pelo menos uma"):
        exportar.montar(banco, hoje, hoje, ["inexistente"])


def test_planilha_excel_de_verdade(banco_com_movimento):
    banco, hoje = banco_com_movimento
    conteudo, nome, mime = exportar.exportar(banco, hoje, hoje, ["resumo", "vendas", "caixas", "produtos"], "xlsx", "Ana")
    assert nome.endswith(".xlsx") and "spreadsheetml" in mime
    wb = load_workbook(io.BytesIO(conteudo))
    assert wb.sheetnames[0] == "Relatório"
    assert wb["Relatório"]["A1"].value == "Relatório — Lanchonete São João"
    assert wb.sheetnames == ["Relatório", "Resumo", "Produtos", "Vendas", "Caixas"]
    vendas = wb["Vendas"]
    cabecalho = [c.value for c in vendas[1]]
    assert cabecalho[:7] == ["Data/hora", "Descrição", "Atendente", "Subtotal", "Desconto", "Acréscimo", "Total"]
    linha = [c for c in vendas[2]]
    assert isinstance(linha[0].value, datetime) and linha[0].number_format == "dd/mm/yyyy hh:mm"
    assert linha[6].value == 40.0 and "R$" in linha[6].number_format      # número de verdade, formatado em reais
    assert "Comanda 1" in linha[1].value
    produtos = wb["Produtos"]
    assert [c.value for c in produtos[2]] == ["X-Burger", 2, 50.0]
    assert produtos.freeze_panes == "A2" and produtos.auto_filter.ref


def test_pdf_de_verdade(banco_com_movimento):
    banco, hoje = banco_com_movimento
    conteudo, nome, mime = exportar.exportar(banco, hoje, hoje, list(exportar.SECOES), "pdf", "Ana")
    assert conteudo.startswith(b"%PDF") and mime == "application/pdf" and nome.endswith(".pdf")
    leitor = PdfReader(io.BytesIO(conteudo))
    texto = "\n".join(pagina.extract_text() for pagina in leitor.pages)
    for esperado in ("Lanchonete São João", "Vendas por forma de pagamento", "R$ 40,00", "Maria Conceição",
                     "cliente desistiu", "compra de gelo", "Fechou o caixa", "Página 1"):
        assert esperado in texto, esperado
    assert "->" in texto or "→" not in texto   # setas do histórico trocadas por "->"


def test_periodo_sem_movimento_gera_arquivo_mesmo_assim(tmp_path):
    banco = Banco(tmp_path / "vazio.db")
    for formato in ("pdf", "xlsx"):
        conteudo, _, _ = exportar.exportar(banco, "2020-01-01", "2020-01-31", ["resumo", "vendas"], formato, "Ana")
        assert len(conteudo) > 500
    texto = PdfReader(io.BytesIO(exportar.exportar(banco, "2020-01-01", "2020-01-31", ["vendas"], "pdf", "Ana")[0])).pages[0].extract_text()
    assert "Nada no período" in texto and "01/01/2020 a 31/01/2020" in texto
    with pytest.raises(ErroNegocio, match="Formato"):
        exportar.exportar(banco, "2020-01-01", "2020-01-31", ["resumo"], "doc", "Ana")
