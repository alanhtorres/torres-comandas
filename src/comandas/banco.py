"""Banco de dados (SQLite) e regras de negócio: cardápio, mesas, pedidos,
senhas de atendimento, chamados de garçom, mídias do painel e configurações.

Tudo passa por uma única conexão protegida por lock — o volume de uma loja é
pequeno, e isso evita qualquer corrida entre caixa, cozinha e clientes
fazendo pedido pelo QR code ao mesmo tempo."""
import json
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

CONFIG_PADRAO = {
    "nome_loja": "Minha Loja",
    # Endereço que vai dentro do QR code das mesas (ex.: http://192.168.0.10:8090).
    # Vazio = detecta o IP deste PC na rede local automaticamente.
    "url_base": "",
    "pedidos_qrcode_ativo": True,
    # Quando a cozinha marca "pronto", já chama no painel sem esperar o caixa.
    "chamar_ao_ficar_pronto": False,
    "som_chamada": True,
    "voz_chamada": False,
    "historico_painel": 8,
    "duracao_foto_painel": 8,
    "mostrar_nome_cliente_painel": True,
    "senha_preferencial_primeiro": True,
    "impressora_cozinha_ativa": False,
    "impressora_cozinha_host": "",
    "impressora_cozinha_porta": 9100,
    "impressora_senhas_ativa": False,
    "impressora_senhas_host": "",
    "impressora_senhas_porta": 9100,
    # 48 colunas = bobina de 80 mm; 32 colunas = bobina de 58 mm.
    "impressora_colunas": 48,
    "impressora_codificacao": "cp850",
}

# Chaves que nunca saem pela API de configuração.
CONFIG_PRIVADA = {"pin_hash", "secret_key"}

STATUS_PEDIDO = ("novo", "preparando", "pronto", "chamado", "entregue", "cancelado")
STATUS_ATIVOS = ("novo", "preparando", "pronto", "chamado")
PREFIXOS_SENHA = {"N": "Normal", "P": "Preferencial"}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS produtos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    categoria TEXT NOT NULL DEFAULT 'Geral',
    preco_centavos INTEGER NOT NULL DEFAULT 0,
    foto TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    ordem INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mesas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT NOT NULL UNIQUE,
    token TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS pedidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    dia TEXT NOT NULL,
    prefixo TEXT NOT NULL DEFAULT '',
    numero INTEGER NOT NULL,
    codigo TEXT NOT NULL,
    origem TEXT NOT NULL,
    mesa TEXT NOT NULL DEFAULT '',
    cliente TEXT NOT NULL DEFAULT '',
    observacao TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    total_centavos INTEGER NOT NULL DEFAULT 0,
    guiche TEXT NOT NULL DEFAULT '',
    chamada_seq INTEGER,
    impressao TEXT NOT NULL DEFAULT '',
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL,
    pronto_em REAL,
    chamado_em REAL
);
CREATE INDEX IF NOT EXISTS idx_pedidos_dia ON pedidos(dia, tipo, prefixo);
CREATE TABLE IF NOT EXISTS pedido_itens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    produto_id INTEGER,
    nome TEXT NOT NULL,
    preco_centavos INTEGER NOT NULL,
    quantidade INTEGER NOT NULL,
    observacao TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chamados_garcom (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mesa TEXT NOT NULL,
    tipo TEXT NOT NULL,
    criado_em REAL NOT NULL,
    atendido_em REAL
);
CREATE TABLE IF NOT EXISTS midias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo TEXT NOT NULL,
    nome_original TEXT NOT NULL DEFAULT '',
    tipo TEXT NOT NULL,
    duracao INTEGER,
    ordem INTEGER NOT NULL DEFAULT 0,
    ativo INTEGER NOT NULL DEFAULT 1
);
"""


class ErroNegocio(Exception):
    """Erro de regra de negócio, com mensagem pronta pra mostrar ao usuário."""


class Banco:
    def __init__(self, caminho: Path, agora: Callable[[], float] = time.time):
        self.lock = threading.RLock()
        self.agora = agora
        self.conn = sqlite3.connect(str(caminho), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(ESQUEMA)
        self.conn.commit()
        # Contador em memória que muda a cada alteração: as telas usam pra
        # saber se precisam redesenhar alguma coisa.
        self.versao = 1

    def _mudou(self) -> None:
        self.versao += 1

    def _dia(self) -> str:
        return datetime.fromtimestamp(self.agora()).strftime("%Y-%m-%d")

    # --- Configurações -------------------------------------------------

    def config(self) -> dict:
        with self.lock:
            dados = dict(CONFIG_PADRAO)
            for linha in self.conn.execute("SELECT chave, valor FROM config"):
                dados[linha["chave"]] = json.loads(linha["valor"])
            return dados

    def config_publica(self) -> dict:
        dados = self.config()
        pin_definido = bool(dados.get("pin_hash"))
        for chave in CONFIG_PRIVADA:
            dados.pop(chave, None)
        dados["pin_definido"] = pin_definido
        return dados

    def salvar_config(self, valores: dict) -> None:
        with self.lock:
            for chave, valor in valores.items():
                if chave not in CONFIG_PADRAO and chave not in CONFIG_PRIVADA:
                    continue
                padrao = CONFIG_PADRAO.get(chave)
                if isinstance(padrao, bool):
                    valor = bool(valor)
                elif isinstance(padrao, int):
                    try:
                        valor = int(valor)
                    except (TypeError, ValueError):
                        raise ErroNegocio(f"Valor inválido para '{chave}'.")
                elif isinstance(padrao, str) or chave in CONFIG_PRIVADA:
                    valor = "" if valor is None else str(valor).strip()
                self.conn.execute(
                    "INSERT INTO config (chave, valor) VALUES (?, ?) "
                    "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                    (chave, json.dumps(valor)),
                )
            self.conn.commit()
            self._mudou()

    def secret_key(self) -> str:
        with self.lock:
            chave = self.config().get("secret_key")
            if not chave:
                chave = secrets.token_hex(32)
                self.salvar_config({"secret_key": chave})
            return chave

    # --- Produtos --------------------------------------------------------

    def listar_produtos(self, somente_ativos: bool = False) -> list:
        with self.lock:
            sql = "SELECT * FROM produtos"
            if somente_ativos:
                sql += " WHERE ativo = 1"
            sql += " ORDER BY categoria COLLATE NOCASE, ordem, nome COLLATE NOCASE"
            return [self._produto_dict(l) for l in self.conn.execute(sql)]

    @staticmethod
    def _produto_dict(linha) -> dict:
        dados = dict(linha)
        dados["ativo"] = bool(dados["ativo"])
        return dados

    def obter_produto(self, produto_id: int) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,)).fetchone()
            return self._produto_dict(linha) if linha else None

    @staticmethod
    def _validar_produto(dados: dict) -> dict:
        nome = str(dados.get("nome") or "").strip()
        if not nome:
            raise ErroNegocio("Informe o nome do produto.")
        try:
            preco = int(dados.get("preco_centavos", 0))
        except (TypeError, ValueError):
            raise ErroNegocio("Preço inválido.")
        if preco < 0:
            raise ErroNegocio("O preço não pode ser negativo.")
        return {
            "nome": nome,
            "descricao": str(dados.get("descricao") or "").strip(),
            "categoria": str(dados.get("categoria") or "").strip() or "Geral",
            "preco_centavos": preco,
            "ativo": 1 if dados.get("ativo", True) else 0,
            "ordem": int(dados.get("ordem") or 0),
        }

    def criar_produto(self, dados: dict) -> dict:
        valores = self._validar_produto(dados)
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO produtos (nome, descricao, categoria, preco_centavos, ativo, ordem) "
                "VALUES (:nome, :descricao, :categoria, :preco_centavos, :ativo, :ordem)",
                valores,
            )
            self.conn.commit()
            self._mudou()
            return self.obter_produto(cur.lastrowid)

    def atualizar_produto(self, produto_id: int, dados: dict) -> dict:
        atual = self.obter_produto(produto_id)
        if not atual:
            raise ErroNegocio("Produto não encontrado.")
        valores = self._validar_produto({**atual, **dados})
        valores["id"] = produto_id
        with self.lock:
            self.conn.execute(
                "UPDATE produtos SET nome = :nome, descricao = :descricao, categoria = :categoria, "
                "preco_centavos = :preco_centavos, ativo = :ativo, ordem = :ordem WHERE id = :id",
                valores,
            )
            self.conn.commit()
            self._mudou()
            return self.obter_produto(produto_id)

    def definir_foto_produto(self, produto_id: int, arquivo: Optional[str]) -> None:
        with self.lock:
            self.conn.execute("UPDATE produtos SET foto = ? WHERE id = ?", (arquivo, produto_id))
            self.conn.commit()
            self._mudou()

    def excluir_produto(self, produto_id: int) -> Optional[str]:
        """Exclui e devolve o nome do arquivo de foto (pra quem chamou apagar)."""
        with self.lock:
            produto = self.obter_produto(produto_id)
            if not produto:
                raise ErroNegocio("Produto não encontrado.")
            # Os itens de pedidos antigos guardam cópia do nome e do preço,
            # então o histórico continua íntegro sem o produto.
            self.conn.execute("UPDATE pedido_itens SET produto_id = NULL WHERE produto_id = ?", (produto_id,))
            self.conn.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
            self.conn.commit()
            self._mudou()
            return produto["foto"]

    # --- Mesas -------------------------------------------------------------

    def listar_mesas(self) -> list:
        with self.lock:
            linhas = self.conn.execute("SELECT * FROM mesas").fetchall()
            mesas = [dict(l) for l in linhas]
            # ordena "2" antes de "10", mas aceita nomes livres ("Varanda 1")
            mesas.sort(key=lambda m: (not m["numero"].isdigit(), int(m["numero"]) if m["numero"].isdigit() else 0, m["numero"].lower()))
            return mesas

    def criar_mesa(self, numero: str) -> dict:
        numero = str(numero or "").strip()
        if not numero:
            raise ErroNegocio("Informe o número/nome da mesa.")
        with self.lock:
            try:
                cur = self.conn.execute(
                    "INSERT INTO mesas (numero, token) VALUES (?, ?)",
                    (numero, secrets.token_urlsafe(9)),
                )
            except sqlite3.IntegrityError:
                raise ErroNegocio(f"A mesa '{numero}' já existe.")
            self.conn.commit()
            self._mudou()
            return dict(self.conn.execute("SELECT * FROM mesas WHERE id = ?", (cur.lastrowid,)).fetchone())

    def criar_mesas_em_lote(self, de: int, ate: int) -> list:
        if de < 1 or ate < de or ate - de > 500:
            raise ErroNegocio("Intervalo de mesas inválido.")
        existentes = {m["numero"] for m in self.listar_mesas()}
        return [self.criar_mesa(str(n)) for n in range(de, ate + 1) if str(n) not in existentes]

    def mesa_por_token(self, token: str) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM mesas WHERE token = ?", (token,)).fetchone()
            return dict(linha) if linha else None

    def obter_mesa(self, mesa_id: int) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM mesas WHERE id = ?", (mesa_id,)).fetchone()
            return dict(linha) if linha else None

    def novo_token_mesa(self, mesa_id: int) -> dict:
        """Invalida o QR code antigo (ex.: foto do QR circulando por aí)."""
        with self.lock:
            if not self.obter_mesa(mesa_id):
                raise ErroNegocio("Mesa não encontrada.")
            self.conn.execute("UPDATE mesas SET token = ? WHERE id = ?", (secrets.token_urlsafe(9), mesa_id))
            self.conn.commit()
            self._mudou()
            return self.obter_mesa(mesa_id)

    def excluir_mesa(self, mesa_id: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM mesas WHERE id = ?", (mesa_id,))
            self.conn.commit()
            self._mudou()

    # --- Pedidos e senhas -------------------------------------------------

    def _proximo_numero(self, tipo: str, prefixo: str, dia: str) -> int:
        linha = self.conn.execute(
            "SELECT MAX(numero) AS n FROM pedidos WHERE dia = ? AND tipo = ? AND prefixo = ?",
            (dia, tipo, prefixo),
        ).fetchone()
        return (linha["n"] or 0) + 1

    def criar_pedido(self, itens: list, origem: str = "caixa", mesa: str = "",
                     cliente: str = "", observacao: str = "") -> dict:
        if not isinstance(itens, list) or not itens:
            raise ErroNegocio("O pedido está vazio.")
        with self.lock:
            linhas_itens = []
            total = 0
            for item in itens:
                try:
                    produto_id = int(item.get("produto_id"))
                    quantidade = int(item.get("quantidade", 1))
                except (TypeError, ValueError, AttributeError):
                    raise ErroNegocio("Item de pedido inválido.")
                if quantidade < 1 or quantidade > 999:
                    raise ErroNegocio("Quantidade inválida.")
                produto = self.obter_produto(produto_id)
                if not produto or not produto["ativo"]:
                    raise ErroNegocio("Um dos produtos não está mais disponível.")
                linhas_itens.append((produto, quantidade, str(item.get("observacao") or "").strip()[:200]))
                total += produto["preco_centavos"] * quantidade

            agora = self.agora()
            dia = self._dia()
            numero = self._proximo_numero("pedido", "", dia)
            cur = self.conn.execute(
                "INSERT INTO pedidos (tipo, dia, prefixo, numero, codigo, origem, mesa, cliente, observacao, "
                "status, total_centavos, criado_em, atualizado_em) "
                "VALUES ('pedido', ?, '', ?, ?, ?, ?, ?, ?, 'novo', ?, ?, ?)",
                (dia, numero, str(numero), origem, str(mesa or "").strip()[:40],
                 str(cliente or "").strip()[:60], str(observacao or "").strip()[:300], total, agora, agora),
            )
            pedido_id = cur.lastrowid
            for produto, quantidade, obs in linhas_itens:
                self.conn.execute(
                    "INSERT INTO pedido_itens (pedido_id, produto_id, nome, preco_centavos, quantidade, observacao) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (pedido_id, produto["id"], produto["nome"], produto["preco_centavos"], quantidade, obs),
                )
            self.conn.commit()
            self._mudou()
            return self.obter_pedido(pedido_id)

    def emitir_senha(self, prefixo: str = "N", origem: str = "caixa") -> dict:
        prefixo = (prefixo or "N").upper()
        if prefixo not in PREFIXOS_SENHA:
            raise ErroNegocio("Tipo de senha inválido.")
        with self.lock:
            agora = self.agora()
            dia = self._dia()
            numero = self._proximo_numero("senha", prefixo, dia)
            cur = self.conn.execute(
                "INSERT INTO pedidos (tipo, dia, prefixo, numero, codigo, origem, status, criado_em, atualizado_em) "
                "VALUES ('senha', ?, ?, ?, ?, ?, 'novo', ?, ?)",
                (dia, prefixo, numero, f"{prefixo}{numero:03d}", origem, agora, agora),
            )
            self.conn.commit()
            self._mudou()
            return self.obter_pedido(cur.lastrowid)

    def obter_pedido(self, pedido_id: int) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
            if not linha:
                return None
            pedido = dict(linha)
            pedido["itens"] = [
                dict(i) for i in self.conn.execute(
                    "SELECT produto_id, nome, preco_centavos, quantidade, observacao "
                    "FROM pedido_itens WHERE pedido_id = ? ORDER BY id", (pedido_id,))
            ]
            return pedido

    def _exigir_pedido(self, pedido_id: int) -> dict:
        pedido = self.obter_pedido(pedido_id)
        if not pedido:
            raise ErroNegocio("Pedido não encontrado.")
        return pedido

    def mudar_status(self, pedido_id: int, status: str) -> dict:
        if status not in STATUS_PEDIDO or status == "chamado":
            raise ErroNegocio("Status inválido.")
        with self.lock:
            pedido = self._exigir_pedido(pedido_id)
            if pedido["status"] in ("entregue", "cancelado") and status != pedido["status"]:
                raise ErroNegocio("Esse pedido já foi finalizado.")
            agora = self.agora()
            campos = {"status": status, "atualizado_em": agora}
            if status == "pronto":
                campos["pronto_em"] = agora
            sets = ", ".join(f"{k} = ?" for k in campos)
            self.conn.execute(f"UPDATE pedidos SET {sets} WHERE id = ?", (*campos.values(), pedido_id))
            self.conn.commit()
            self._mudou()
        if status == "pronto" and pedido["tipo"] == "pedido" and self.config()["chamar_ao_ficar_pronto"]:
            return self.chamar(pedido_id)
        return self.obter_pedido(pedido_id)

    def chamar(self, pedido_id: int, guiche: str = "") -> dict:
        """Coloca o pedido/senha no painel (ou chama de novo, se já estava)."""
        with self.lock:
            pedido = self._exigir_pedido(pedido_id)
            if pedido["status"] == "cancelado":
                raise ErroNegocio("Esse pedido foi cancelado.")
            linha = self.conn.execute("SELECT MAX(chamada_seq) AS s FROM pedidos").fetchone()
            seq = (linha["s"] or 0) + 1
            agora = self.agora()
            self.conn.execute(
                "UPDATE pedidos SET status = 'chamado', chamada_seq = ?, chamado_em = ?, atualizado_em = ?, "
                "guiche = ?, pronto_em = COALESCE(pronto_em, ?) WHERE id = ?",
                (seq, agora, agora, str(guiche or pedido["guiche"] or "").strip()[:20], agora, pedido_id),
            )
            self.conn.commit()
            self._mudou()
            return self.obter_pedido(pedido_id)

    def chamar_proxima_senha(self, guiche: str = "") -> Optional[dict]:
        """Chama a próxima senha da fila. A senha que estava sendo atendida
        nesse mesmo guichê é dada como atendida automaticamente."""
        guiche = str(guiche or "").strip()[:20]
        with self.lock:
            dia = self._dia()
            if guiche:
                self.conn.execute(
                    "UPDATE pedidos SET status = 'entregue', atualizado_em = ? "
                    "WHERE tipo = 'senha' AND status = 'chamado' AND guiche = ?",
                    (self.agora(), guiche),
                )
            ordem = "CASE prefixo WHEN 'P' THEN 0 ELSE 1 END, " if self.config()["senha_preferencial_primeiro"] else ""
            linha = self.conn.execute(
                f"SELECT id FROM pedidos WHERE tipo = 'senha' AND status = 'novo' AND dia = ? "
                f"ORDER BY {ordem}criado_em, id LIMIT 1",
                (dia,),
            ).fetchone()
            if not linha:
                self.conn.commit()
                self._mudou()
                return None
            return self.chamar(linha["id"], guiche)

    def registrar_impressao(self, pedido_id: int, resultado: str) -> None:
        with self.lock:
            self.conn.execute("UPDATE pedidos SET impressao = ? WHERE id = ?", (resultado[:200], pedido_id))
            self.conn.commit()
            self._mudou()

    def listar_pedidos(self, statuses=STATUS_ATIVOS, tipo: Optional[str] = None,
                       mesa: Optional[str] = None, somente_hoje: bool = True) -> list:
        with self.lock:
            sql = f"SELECT id FROM pedidos WHERE status IN ({','.join('?' * len(statuses))})"
            params = list(statuses)
            if tipo:
                sql += " AND tipo = ?"
                params.append(tipo)
            if mesa is not None:
                sql += " AND mesa = ?"
                params.append(mesa)
            if somente_hoje:
                sql += " AND dia = ?"
                params.append(self._dia())
            sql += " ORDER BY criado_em, id"
            return [self.obter_pedido(l["id"]) for l in self.conn.execute(sql, params).fetchall()]

    def chamadas_recentes(self, limite: int = 8) -> list:
        """Últimas chamadas de hoje, a mais recente primeiro (painel)."""
        with self.lock:
            linhas = self.conn.execute(
                "SELECT id, tipo, codigo, cliente, mesa, guiche, status, chamada_seq, chamado_em FROM pedidos "
                "WHERE chamada_seq IS NOT NULL AND status IN ('chamado', 'entregue') AND dia = ? "
                "ORDER BY chamada_seq DESC LIMIT ?",
                (self._dia(), max(1, min(int(limite), 50))),
            ).fetchall()
            return [dict(l) for l in linhas]

    def resumo_senhas(self) -> dict:
        with self.lock:
            fila = {p: 0 for p in PREFIXOS_SENHA}
            for linha in self.conn.execute(
                "SELECT prefixo, COUNT(*) AS n FROM pedidos WHERE tipo = 'senha' AND status = 'novo' AND dia = ? "
                "GROUP BY prefixo", (self._dia(),)
            ):
                fila[linha["prefixo"]] = linha["n"]
            return {"aguardando": fila, "total": sum(fila.values())}

    # --- Chamados de garçom ----------------------------------------------

    def chamar_garcom(self, mesa: str, tipo: str = "garcom") -> dict:
        if tipo not in ("garcom", "conta"):
            raise ErroNegocio("Tipo de chamado inválido.")
        with self.lock:
            # Cliente apertando o botão várias vezes não gera vários chamados.
            existente = self.conn.execute(
                "SELECT * FROM chamados_garcom WHERE mesa = ? AND tipo = ? AND atendido_em IS NULL",
                (mesa, tipo),
            ).fetchone()
            if existente:
                return dict(existente)
            cur = self.conn.execute(
                "INSERT INTO chamados_garcom (mesa, tipo, criado_em) VALUES (?, ?, ?)",
                (mesa, tipo, self.agora()),
            )
            self.conn.commit()
            self._mudou()
            return dict(self.conn.execute("SELECT * FROM chamados_garcom WHERE id = ?", (cur.lastrowid,)).fetchone())

    def chamados_pendentes(self, mesa: Optional[str] = None) -> list:
        with self.lock:
            sql = "SELECT * FROM chamados_garcom WHERE atendido_em IS NULL"
            params = []
            if mesa is not None:
                sql += " AND mesa = ?"
                params.append(mesa)
            return [dict(l) for l in self.conn.execute(sql + " ORDER BY criado_em", params)]

    def atender_chamado(self, chamado_id: int) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE chamados_garcom SET atendido_em = ? WHERE id = ? AND atendido_em IS NULL",
                (self.agora(), chamado_id),
            )
            self.conn.commit()
            self._mudou()

    # --- Mídias do painel ---------------------------------------------

    def listar_midias(self, somente_ativas: bool = False) -> list:
        with self.lock:
            sql = "SELECT * FROM midias"
            if somente_ativas:
                sql += " WHERE ativo = 1"
            linhas = self.conn.execute(sql + " ORDER BY ordem, id").fetchall()
            return [{**dict(l), "ativo": bool(l["ativo"])} for l in linhas]

    def adicionar_midia(self, arquivo: str, tipo: str, nome_original: str = "") -> dict:
        with self.lock:
            linha = self.conn.execute("SELECT MAX(ordem) AS o FROM midias").fetchone()
            cur = self.conn.execute(
                "INSERT INTO midias (arquivo, nome_original, tipo, ordem) VALUES (?, ?, ?, ?)",
                (arquivo, nome_original[:200], tipo, (linha["o"] or 0) + 1),
            )
            self.conn.commit()
            self._mudou()
            return dict(self.conn.execute("SELECT * FROM midias WHERE id = ?", (cur.lastrowid,)).fetchone())

    def atualizar_midia(self, midia_id: int, dados: dict) -> None:
        with self.lock:
            if "ativo" in dados:
                self.conn.execute("UPDATE midias SET ativo = ? WHERE id = ?", (1 if dados["ativo"] else 0, midia_id))
            if "duracao" in dados:
                duracao = dados["duracao"]
                duracao = int(duracao) if duracao not in (None, "", 0) else None
                self.conn.execute("UPDATE midias SET duracao = ? WHERE id = ?", (duracao, midia_id))
            if "ordem" in dados:
                self.conn.execute("UPDATE midias SET ordem = ? WHERE id = ?", (int(dados["ordem"]), midia_id))
            self.conn.commit()
            self._mudou()

    def mover_midia(self, midia_id: int, direcao: int) -> None:
        with self.lock:
            midias = self.listar_midias()
            ids = [m["id"] for m in midias]
            if midia_id not in ids:
                raise ErroNegocio("Mídia não encontrada.")
            i = ids.index(midia_id)
            j = i + (1 if direcao > 0 else -1)
            if 0 <= j < len(ids):
                ids[i], ids[j] = ids[j], ids[i]
            for ordem, mid in enumerate(ids, start=1):
                self.conn.execute("UPDATE midias SET ordem = ? WHERE id = ?", (ordem, mid))
            self.conn.commit()
            self._mudou()

    def excluir_midia(self, midia_id: int) -> Optional[str]:
        with self.lock:
            linha = self.conn.execute("SELECT arquivo FROM midias WHERE id = ?", (midia_id,)).fetchone()
            if not linha:
                return None
            self.conn.execute("DELETE FROM midias WHERE id = ?", (midia_id,))
            self.conn.commit()
            self._mudou()
            return linha["arquivo"]
