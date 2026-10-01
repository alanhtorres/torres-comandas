"""Banco de dados (SQLite) e regras de negócio: usuários e permissões,
cardápio, mesas, pedidos, chamados de garçom, controle de caixa (abertura,
recebimentos, sangria/suprimento, fechamento), relatórios, histórico de
ações (auditoria), mídias do painel e configurações.

Tudo passa por uma única conexão protegida por lock, e cada operação que
altera dados grava, na MESMA transação, o registro de quem fez o quê no
histórico (auditoria) — ou as duas coisas ficam salvas, ou nenhuma."""
import csv
import io
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from werkzeug.security import check_password_hash, generate_password_hash

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
    # Sugestão do botão "taxa de serviço" na hora de receber (0 = esconde).
    "taxa_servico_percentual": 10,
    "impressora_cozinha_ativa": False,
    "impressora_cozinha_host": "",
    "impressora_cozinha_porta": 9100,
    # Impressora do caixa: conferência de conta e fechamento de caixa.
    "impressora_caixa_ativa": False,
    "impressora_caixa_host": "",
    "impressora_caixa_porta": 9100,
    # 48 colunas = bobina de 80 mm; 32 colunas = bobina de 58 mm.
    "impressora_colunas": 48,
    "impressora_codificacao": "cp850",
}

# Chaves que nunca saem pela API de configuração.
CONFIG_PRIVADA = {"secret_key"}

# O que cada usuário pode acessar — o administrador marca uma a uma.
PERMISSOES = {
    "pedidos": "Caixa: lançar e acompanhar pedidos, chamar no painel, atender garçom",
    "cozinha": "Tela da cozinha (iniciar preparo / pronto)",
    "receber": "Receber pagamentos",
    "caixa": "Abrir e fechar o caixa, sangria e suprimento",
    "cancelar": "Cancelar pedidos e estornar pagamentos",
    "cardapio": "Cadastro de produtos (cardápio)",
    "mesas": "Mesas e QR codes",
    "midias": "Fotos e vídeos do painel",
    "configuracoes": "Configurações do sistema e impressoras",
    "relatorios": "Relatórios financeiros e de vendas",
    "historico": "Histórico de ações dos usuários",
    "usuarios": "Usuários e permissões",
}
# Permissões que dão acesso à tela de administração.
PERMISSOES_ADMIN = ("cardapio", "mesas", "midias", "configuracoes", "relatorios", "historico", "usuarios")

# Modelos prontos para preencher as permissões de um usuário novo.
MODELOS = {
    "admin": ("Administrador", list(PERMISSOES)),
    "caixa": ("Caixa", ["pedidos", "cozinha", "receber", "caixa"]),
    "garcom": ("Garçom", ["pedidos"]),
    "cozinha": ("Cozinha", ["cozinha"]),
}

FORMAS_PAGAMENTO = {
    "dinheiro": "Dinheiro",
    "pix": "Pix",
    "debito": "Cartão de débito",
    "credito": "Cartão de crédito",
    "vale": "Vale-refeição",
    "outro": "Outro",
}

STATUS_PEDIDO = ("novo", "preparando", "pronto", "chamado", "entregue", "cancelado")
STATUS_ATIVOS = ("novo", "preparando", "pronto", "chamado")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    senha_hash TEXT NOT NULL,
    permissoes TEXT NOT NULL DEFAULT '[]',
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em REAL NOT NULL,
    usuario_id INTEGER,
    usuario_nome TEXT NOT NULL,
    acao TEXT NOT NULL,
    detalhes TEXT NOT NULL DEFAULT '',
    pedido_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_auditoria_data ON auditoria(criado_em);
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
-- prefixo/guiche (e tipo = 'senha'): sobras das senhas de atendimento da
-- versão 1.x, mantidas só para bancos antigos abrirem sem erro.
CREATE TABLE IF NOT EXISTS pedidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL DEFAULT 'pedido',
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
CREATE TABLE IF NOT EXISTS sessoes_caixa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aberto_por INTEGER,
    aberto_por_nome TEXT NOT NULL,
    aberto_em REAL NOT NULL,
    valor_abertura INTEGER NOT NULL DEFAULT 0,
    fechado_por INTEGER,
    fechado_por_nome TEXT NOT NULL DEFAULT '',
    fechado_em REAL,
    valor_contado INTEGER,
    esperado_dinheiro INTEGER,
    diferenca INTEGER,
    observacao TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS movimentos_caixa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id INTEGER NOT NULL REFERENCES sessoes_caixa(id),
    tipo TEXT NOT NULL,
    valor INTEGER NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    usuario_id INTEGER,
    usuario_nome TEXT NOT NULL,
    criado_em REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS recebimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id INTEGER NOT NULL REFERENCES sessoes_caixa(id),
    usuario_id INTEGER,
    usuario_nome TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    subtotal INTEGER NOT NULL,
    desconto INTEGER NOT NULL DEFAULT 0,
    acrescimo INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL,
    troco INTEGER NOT NULL DEFAULT 0,
    criado_em REAL NOT NULL,
    estornado_em REAL,
    estornado_por_nome TEXT NOT NULL DEFAULT '',
    motivo_estorno TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_recebimentos_data ON recebimentos(criado_em);
CREATE TABLE IF NOT EXISTS recebimento_formas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recebimento_id INTEGER NOT NULL REFERENCES recebimentos(id),
    forma TEXT NOT NULL,
    valor INTEGER NOT NULL
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

# Colunas acrescentadas depois da versão 1.0 — bancos antigos ganham estas
# colunas automaticamente ao abrir (os dados existentes são preservados).
COLUNAS_NOVAS = {
    "pedidos": {
        "usuario_id": "INTEGER",
        "usuario_nome": "TEXT NOT NULL DEFAULT ''",
        "recebimento_id": "INTEGER",
        "cancelado_por_nome": "TEXT NOT NULL DEFAULT ''",
        "motivo_cancelamento": "TEXT NOT NULL DEFAULT ''",
    },
}


class ErroNegocio(Exception):
    """Erro de regra de negócio, com mensagem pronta pra mostrar ao usuário."""


def _centavos(valor, nome: str, permitir_zero: bool = True) -> int:
    try:
        v = int(valor or 0)
    except (TypeError, ValueError):
        raise ErroNegocio(f"Valor inválido em '{nome}'.")
    if v < 0 or (v == 0 and not permitir_zero):
        raise ErroNegocio(f"Valor inválido em '{nome}'.")
    return v


def moeda(centavos: int) -> str:
    texto = f"{abs(centavos) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if centavos < 0 else "R$ ") + texto


def _texto(valor, limite: int) -> str:
    return str(valor or "").strip()[:limite]


class Banco:
    def __init__(self, caminho: Path, agora: Callable[[], float] = time.time):
        self.caminho = Path(caminho)
        self.lock = threading.RLock()
        self.agora = agora
        self.conn = sqlite3.connect(str(caminho), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        # FULL: cada venda/recebimento confirmado já está gravado no disco,
        # mesmo que falte energia no segundo seguinte.
        self.conn.execute("PRAGMA synchronous = FULL")
        self.conn.executescript(ESQUEMA)
        self._migrar()
        self.conn.commit()
        # Contador em memória que muda a cada alteração: as telas usam pra
        # saber se precisam redesenhar alguma coisa.
        self.versao = 1

    def _migrar(self) -> None:
        for tabela, colunas in COLUNAS_NOVAS.items():
            existentes = {l["name"] for l in self.conn.execute(f"PRAGMA table_info({tabela})")}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    self.conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")

    @contextmanager
    def _transacao(self):
        """Tudo dentro do bloco é gravado junto (ou nada, se der erro)."""
        with self.lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            self.versao += 1

    def _registrar(self, ator: Optional[dict], acao: str, detalhes: str = "", pedido_id: Optional[int] = None) -> None:
        """Grava no histórico. Chamar só dentro de uma _transacao()."""
        self.conn.execute(
            "INSERT INTO auditoria (criado_em, usuario_id, usuario_nome, acao, detalhes, pedido_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self.agora(), (ator or {}).get("id"), (ator or {}).get("nome") or "Sistema", acao, detalhes[:1000], pedido_id),
        )

    def _dia(self, ts: Optional[float] = None) -> str:
        return datetime.fromtimestamp(self.agora() if ts is None else ts).strftime("%Y-%m-%d")

    def fazer_backup(self, destino: Path) -> None:
        """Cópia consistente do banco (mesmo com o sistema em uso)."""
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(".tmp")
        with self.lock:
            copia = sqlite3.connect(str(temporario))
            try:
                self.conn.backup(copia)
            finally:
                copia.close()
        temporario.replace(destino)

    # --- Configurações -------------------------------------------------

    def config(self) -> dict:
        with self.lock:
            dados = dict(CONFIG_PADRAO)
            for linha in self.conn.execute("SELECT chave, valor FROM config"):
                if linha["chave"] in CONFIG_PADRAO or linha["chave"] in CONFIG_PRIVADA:
                    dados[linha["chave"]] = json.loads(linha["valor"])
            return dados

    def config_publica(self) -> dict:
        dados = self.config()
        for chave in CONFIG_PRIVADA:
            dados.pop(chave, None)
        return dados

    def salvar_config(self, valores: dict, por: Optional[dict] = None) -> None:
        atual = self.config()
        mudancas = []
        with self._transacao():
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
                else:
                    valor = "" if valor is None else str(valor).strip()
                self.conn.execute(
                    "INSERT INTO config (chave, valor) VALUES (?, ?) "
                    "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                    (chave, json.dumps(valor)),
                )
                if chave not in CONFIG_PRIVADA and atual.get(chave) != valor:
                    mudancas.append(f"{chave}: {atual.get(chave)!r} → {valor!r}")
            if mudancas:
                self._registrar(por, "Alterou configurações", "; ".join(mudancas))

    def secret_key(self) -> str:
        chave = self.config().get("secret_key")
        if not chave:
            chave = secrets.token_hex(32)
            self.salvar_config({"secret_key": chave})
        return chave

    # --- Usuários e permissões -----------------------------------------

    @staticmethod
    def _usuario_dict(linha) -> dict:
        dados = dict(linha)
        dados.pop("senha_hash", None)
        dados["ativo"] = bool(dados["ativo"])
        dados["permissoes"] = [p for p in json.loads(dados["permissoes"]) if p in PERMISSOES]
        return dados

    def existe_usuario(self) -> bool:
        with self.lock:
            return self.conn.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None

    def listar_usuarios(self) -> list:
        with self.lock:
            return [self._usuario_dict(l) for l in self.conn.execute("SELECT * FROM usuarios ORDER BY nome COLLATE NOCASE")]

    def obter_usuario(self, usuario_id) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
            return self._usuario_dict(linha) if linha else None

    @staticmethod
    def _validar_senha(senha) -> str:
        senha = str(senha or "")
        if len(senha) < 4:
            raise ErroNegocio("A senha precisa ter pelo menos 4 caracteres.")
        return senha

    @staticmethod
    def _validar_permissoes(permissoes) -> list:
        if not isinstance(permissoes, list):
            raise ErroNegocio("Permissões inválidas.")
        return [p for p in PERMISSOES if p in permissoes]

    def _admins_ativos(self, excluir_id: Optional[int] = None) -> int:
        total = 0
        for u in self.listar_usuarios():
            if u["ativo"] and "usuarios" in u["permissoes"] and u["id"] != excluir_id:
                total += 1
        return total

    def criar_usuario(self, dados: dict, por: Optional[dict] = None) -> dict:
        nome = _texto(dados.get("nome"), 60)
        login = _texto(dados.get("login"), 30).lower()
        if not nome or not login:
            raise ErroNegocio("Informe o nome e o usuário (login).")
        if " " in login:
            raise ErroNegocio("O usuário (login) não pode ter espaços.")
        senha = self._validar_senha(dados.get("senha"))
        permissoes = self._validar_permissoes(dados.get("permissoes", []))
        with self._transacao():
            try:
                cur = self.conn.execute(
                    "INSERT INTO usuarios (nome, login, senha_hash, permissoes, ativo, criado_em) VALUES (?, ?, ?, ?, 1, ?)",
                    (nome, login, generate_password_hash(senha), json.dumps(permissoes), self.agora()),
                )
            except sqlite3.IntegrityError:
                raise ErroNegocio(f"Já existe um usuário com o login '{login}'.")
            self._registrar(por, "Criou usuário", f"{nome} ({login}) — permissões: {', '.join(permissoes) or 'nenhuma'}")
        return self.obter_usuario(cur.lastrowid)

    def criar_primeiro_admin(self, dados: dict) -> dict:
        with self.lock:
            if self.existe_usuario():
                raise ErroNegocio("O administrador já foi criado.")
            usuario = self.criar_usuario({**dados, "permissoes": list(PERMISSOES)})
        with self._transacao():
            self._registrar(usuario, "Criou o primeiro administrador no primeiro acesso")
        return usuario

    def atualizar_usuario(self, usuario_id: int, dados: dict, por: Optional[dict] = None) -> dict:
        atual = self.obter_usuario(usuario_id)
        if not atual:
            raise ErroNegocio("Usuário não encontrado.")
        nome = _texto(dados.get("nome", atual["nome"]), 60) or atual["nome"]
        permissoes = self._validar_permissoes(dados.get("permissoes", atual["permissoes"]))
        ativo = bool(dados.get("ativo", atual["ativo"]))
        tira_admin = atual["ativo"] and "usuarios" in atual["permissoes"] and (not ativo or "usuarios" not in permissoes)
        if tira_admin and self._admins_ativos(excluir_id=usuario_id) == 0:
            raise ErroNegocio("Precisa existir pelo menos um usuário ativo com a permissão 'Usuários e permissões'.")
        mudancas = []
        if nome != atual["nome"]:
            mudancas.append(f"nome: {atual['nome']} → {nome}")
        if set(permissoes) != set(atual["permissoes"]):
            mudancas.append(f"permissões: {', '.join(permissoes) or 'nenhuma'}")
        if ativo != atual["ativo"]:
            mudancas.append("reativado" if ativo else "desativado")
        with self._transacao():
            self.conn.execute(
                "UPDATE usuarios SET nome = ?, permissoes = ?, ativo = ? WHERE id = ?",
                (nome, json.dumps(permissoes), 1 if ativo else 0, usuario_id),
            )
            if dados.get("senha"):
                self.conn.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                                  (generate_password_hash(self._validar_senha(dados["senha"])), usuario_id))
                mudancas.append("senha redefinida")
            if mudancas:
                self._registrar(por, "Alterou usuário", f"{atual['login']}: " + "; ".join(mudancas))
        return self.obter_usuario(usuario_id)

    def trocar_propria_senha(self, usuario: dict, senha_atual: str, nova: str) -> None:
        with self.lock:
            linha = self.conn.execute("SELECT senha_hash FROM usuarios WHERE id = ?", (usuario["id"],)).fetchone()
        if not linha or not check_password_hash(linha["senha_hash"], senha_atual or ""):
            raise ErroNegocio("Senha atual incorreta.")
        with self._transacao():
            self.conn.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                              (generate_password_hash(self._validar_senha(nova)), usuario["id"]))
            self._registrar(usuario, "Trocou a própria senha")

    def autenticar(self, login: str, senha: str) -> Optional[dict]:
        login = _texto(login, 30).lower()
        with self.lock:
            linha = self.conn.execute("SELECT * FROM usuarios WHERE login = ?", (login,)).fetchone()
        ok = bool(linha) and bool(linha["ativo"]) and check_password_hash(linha["senha_hash"], senha or "")
        with self._transacao():
            if ok:
                usuario = self._usuario_dict(linha)
                self._registrar(usuario, "Entrou no sistema")
                return usuario
            motivo = "usuário desativado" if linha and not linha["ativo"] else "usuário ou senha incorretos"
            self._registrar(None, "Tentativa de login recusada", f"login '{login}': {motivo}")
        return None

    def registrar_saida(self, usuario: dict) -> None:
        with self._transacao():
            self._registrar(usuario, "Saiu do sistema")

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
        nome = _texto(dados.get("nome"), 80)
        if not nome:
            raise ErroNegocio("Informe o nome do produto.")
        return {
            "nome": nome,
            "descricao": _texto(dados.get("descricao"), 200),
            "categoria": _texto(dados.get("categoria"), 40) or "Geral",
            "preco_centavos": _centavos(dados.get("preco_centavos", 0), "preço"),
            "ativo": 1 if dados.get("ativo", True) else 0,
            "ordem": int(dados.get("ordem") or 0),
        }

    def criar_produto(self, dados: dict, por: Optional[dict] = None) -> dict:
        valores = self._validar_produto(dados)
        with self._transacao():
            cur = self.conn.execute(
                "INSERT INTO produtos (nome, descricao, categoria, preco_centavos, ativo, ordem) "
                "VALUES (:nome, :descricao, :categoria, :preco_centavos, :ativo, :ordem)",
                valores,
            )
            self._registrar(por, "Cadastrou produto", f"{valores['nome']} — {moeda(valores['preco_centavos'])}")
        return self.obter_produto(cur.lastrowid)

    def atualizar_produto(self, produto_id: int, dados: dict, por: Optional[dict] = None) -> dict:
        atual = self.obter_produto(produto_id)
        if not atual:
            raise ErroNegocio("Produto não encontrado.")
        valores = self._validar_produto({**atual, **dados})
        valores["id"] = produto_id
        mudancas = []
        for campo, rotulo in (("nome", "nome"), ("categoria", "categoria"), ("descricao", "descrição")):
            if valores[campo] != atual[campo]:
                mudancas.append(f"{rotulo}: {atual[campo]} → {valores[campo]}")
        if valores["preco_centavos"] != atual["preco_centavos"]:
            mudancas.append(f"preço: {moeda(atual['preco_centavos'])} → {moeda(valores['preco_centavos'])}")
        if bool(valores["ativo"]) != atual["ativo"]:
            mudancas.append("disponível" if valores["ativo"] else "pausado (indisponível)")
        with self._transacao():
            self.conn.execute(
                "UPDATE produtos SET nome = :nome, descricao = :descricao, categoria = :categoria, "
                "preco_centavos = :preco_centavos, ativo = :ativo, ordem = :ordem WHERE id = :id",
                valores,
            )
            if mudancas:
                self._registrar(por, "Alterou produto", f"{atual['nome']}: " + "; ".join(mudancas))
        return self.obter_produto(produto_id)

    def definir_foto_produto(self, produto_id: int, arquivo: Optional[str], por: Optional[dict] = None) -> None:
        produto = self.obter_produto(produto_id)
        with self._transacao():
            self.conn.execute("UPDATE produtos SET foto = ? WHERE id = ?", (arquivo, produto_id))
            self._registrar(por, "Trocou foto do produto" if arquivo else "Removeu foto do produto",
                            produto["nome"] if produto else str(produto_id))

    def excluir_produto(self, produto_id: int, por: Optional[dict] = None) -> Optional[str]:
        """Exclui e devolve o nome do arquivo de foto (pra quem chamou apagar)."""
        produto = self.obter_produto(produto_id)
        if not produto:
            raise ErroNegocio("Produto não encontrado.")
        with self._transacao():
            # Os itens de pedidos antigos guardam cópia do nome e do preço,
            # então o histórico e os relatórios continuam íntegros sem o produto.
            self.conn.execute("UPDATE pedido_itens SET produto_id = NULL WHERE produto_id = ?", (produto_id,))
            self.conn.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
            self._registrar(por, "Excluiu produto", produto["nome"])
        return produto["foto"]

    # --- Mesas -------------------------------------------------------------

    def listar_mesas(self) -> list:
        with self.lock:
            mesas = [dict(l) for l in self.conn.execute("SELECT * FROM mesas")]
        # ordena "2" antes de "10", mas aceita nomes livres ("Varanda 1")
        mesas.sort(key=lambda m: (not m["numero"].isdigit(), int(m["numero"]) if m["numero"].isdigit() else 0, m["numero"].lower()))
        return mesas

    def _inserir_mesa(self, numero: str) -> int:
        try:
            cur = self.conn.execute("INSERT INTO mesas (numero, token) VALUES (?, ?)", (numero, secrets.token_urlsafe(9)))
        except sqlite3.IntegrityError:
            raise ErroNegocio(f"A mesa '{numero}' já existe.")
        return cur.lastrowid

    def criar_mesa(self, numero: str, por: Optional[dict] = None) -> dict:
        numero = _texto(numero, 40)
        if not numero:
            raise ErroNegocio("Informe o número/nome da mesa.")
        with self._transacao():
            mesa_id = self._inserir_mesa(numero)
            self._registrar(por, "Criou mesa", numero)
        return self.obter_mesa(mesa_id)

    def criar_mesas_em_lote(self, de: int, ate: int, por: Optional[dict] = None) -> int:
        if de < 1 or ate < de or ate - de > 500:
            raise ErroNegocio("Intervalo de mesas inválido.")
        existentes = {m["numero"] for m in self.listar_mesas()}
        novas = [str(n) for n in range(de, ate + 1) if str(n) not in existentes]
        with self._transacao():
            for numero in novas:
                self._inserir_mesa(numero)
            if novas:
                self._registrar(por, "Criou mesas", f"{len(novas)} mesa(s): {novas[0]} a {novas[-1]}")
        return len(novas)

    def mesa_por_token(self, token: str) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM mesas WHERE token = ?", (token,)).fetchone()
            return dict(linha) if linha else None

    def obter_mesa(self, mesa_id: int) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM mesas WHERE id = ?", (mesa_id,)).fetchone()
            return dict(linha) if linha else None

    def novo_token_mesa(self, mesa_id: int, por: Optional[dict] = None) -> dict:
        """Invalida o QR code antigo (ex.: foto do QR circulando por aí)."""
        mesa = self.obter_mesa(mesa_id)
        if not mesa:
            raise ErroNegocio("Mesa não encontrada.")
        with self._transacao():
            self.conn.execute("UPDATE mesas SET token = ? WHERE id = ?", (secrets.token_urlsafe(9), mesa_id))
            self._registrar(por, "Gerou novo QR code da mesa", mesa["numero"])
        return self.obter_mesa(mesa_id)

    def excluir_mesa(self, mesa_id: int, por: Optional[dict] = None) -> None:
        mesa = self.obter_mesa(mesa_id)
        if not mesa:
            return
        with self._transacao():
            self.conn.execute("DELETE FROM mesas WHERE id = ?", (mesa_id,))
            self._registrar(por, "Excluiu mesa", mesa["numero"])

    # --- Pedidos -------------------------------------------------------

    def criar_pedido(self, itens: list, origem: str = "caixa", mesa: str = "",
                     cliente: str = "", observacao: str = "", por: Optional[dict] = None) -> dict:
        if not isinstance(itens, list) or not itens:
            raise ErroNegocio("O pedido está vazio.")
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
            linhas_itens.append((produto, quantidade, _texto(item.get("observacao"), 200)))
            total += produto["preco_centavos"] * quantidade

        with self._transacao():
            agora = self.agora()
            dia = self._dia()
            linha = self.conn.execute("SELECT MAX(numero) AS n FROM pedidos WHERE dia = ? AND tipo = 'pedido'", (dia,)).fetchone()
            numero = (linha["n"] or 0) + 1
            cur = self.conn.execute(
                "INSERT INTO pedidos (tipo, dia, numero, codigo, origem, mesa, cliente, observacao, status, "
                "total_centavos, criado_em, atualizado_em, usuario_id, usuario_nome) "
                "VALUES ('pedido', ?, ?, ?, ?, ?, ?, ?, 'novo', ?, ?, ?, ?, ?)",
                (dia, numero, str(numero), origem, _texto(mesa, 40), _texto(cliente, 60), _texto(observacao, 300),
                 total, agora, agora, (por or {}).get("id"), (por or {}).get("nome") or ""),
            )
            pedido_id = cur.lastrowid
            for produto, quantidade, obs in linhas_itens:
                self.conn.execute(
                    "INSERT INTO pedido_itens (pedido_id, produto_id, nome, preco_centavos, quantidade, observacao) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (pedido_id, produto["id"], produto["nome"], produto["preco_centavos"], quantidade, obs),
                )
            resumo = ", ".join(f"{q}x {p['nome']}" for p, q, _ in linhas_itens)
            onde = f" — mesa {mesa}" if mesa else ""
            self._registrar(por, "Lançou pedido", f"Nº {numero}{onde}: {resumo} ({moeda(total)})", pedido_id)
        return self.obter_pedido(pedido_id)

    def obter_pedido(self, pedido_id: int) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
            if not linha:
                return None
            pedido = dict(linha)
            pedido["pago"] = pedido["recebimento_id"] is not None
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

    NOMES_STATUS = {"preparando": "Iniciou preparo", "pronto": "Marcou pronto", "entregue": "Marcou entregue",
                    "novo": "Voltou para a fila"}

    def mudar_status(self, pedido_id: int, status: str, por: Optional[dict] = None, motivo: str = "") -> dict:
        if status not in STATUS_PEDIDO or status == "chamado":
            raise ErroNegocio("Status inválido.")
        pedido = self._exigir_pedido(pedido_id)
        if pedido["status"] in ("entregue", "cancelado") and status != pedido["status"]:
            raise ErroNegocio("Esse pedido já foi finalizado.")
        if status == "cancelado":
            if pedido["pago"]:
                raise ErroNegocio("Esse pedido já foi pago. Estorne o pagamento antes de cancelar.")
            motivo = _texto(motivo, 200)
            if not motivo:
                raise ErroNegocio("Informe o motivo do cancelamento.")
        with self._transacao():
            agora = self.agora()
            campos = {"status": status, "atualizado_em": agora}
            if status == "pronto":
                campos["pronto_em"] = agora
            if status == "cancelado":
                campos["cancelado_por_nome"] = (por or {}).get("nome") or "Sistema"
                campos["motivo_cancelamento"] = motivo
            sets = ", ".join(f"{k} = ?" for k in campos)
            self.conn.execute(f"UPDATE pedidos SET {sets} WHERE id = ?", (*campos.values(), pedido_id))
            if status == "cancelado":
                self._registrar(por, "Cancelou pedido", f"Nº {pedido['codigo']} ({moeda(pedido['total_centavos'])}) — motivo: {motivo}", pedido_id)
            else:
                self._registrar(por, self.NOMES_STATUS.get(status, status), f"Pedido nº {pedido['codigo']}", pedido_id)
        if status == "pronto" and self.config()["chamar_ao_ficar_pronto"]:
            return self.chamar(pedido_id, por=None)
        return self.obter_pedido(pedido_id)

    def chamar(self, pedido_id: int, por: Optional[dict] = None) -> dict:
        """Coloca o pedido no painel (ou chama de novo, se já estava)."""
        pedido = self._exigir_pedido(pedido_id)
        if pedido["status"] == "cancelado":
            raise ErroNegocio("Esse pedido foi cancelado.")
        with self._transacao():
            linha = self.conn.execute("SELECT MAX(chamada_seq) AS s FROM pedidos").fetchone()
            agora = self.agora()
            self.conn.execute(
                "UPDATE pedidos SET status = 'chamado', chamada_seq = ?, chamado_em = ?, atualizado_em = ?, "
                "pronto_em = COALESCE(pronto_em, ?) WHERE id = ?",
                ((linha["s"] or 0) + 1, agora, agora, agora, pedido_id),
            )
            acao = "Chamou de novo no painel" if pedido["status"] == "chamado" else "Chamou no painel"
            self._registrar(por, acao, f"Pedido nº {pedido['codigo']}", pedido_id)
        return self.obter_pedido(pedido_id)

    def registrar_impressao(self, pedido_id: int, resultado: str) -> None:
        # Status técnico da impressora (não é uma ação de usuário).
        with self.lock:
            self.conn.execute("UPDATE pedidos SET impressao = ? WHERE id = ?", (resultado[:200], pedido_id))
            self.conn.commit()
            self.versao += 1

    def registrar_acao(self, por: Optional[dict], acao: str, detalhes: str = "", pedido_id: Optional[int] = None) -> None:
        with self._transacao():
            self._registrar(por, acao, detalhes, pedido_id)

    def listar_pedidos(self, statuses=STATUS_ATIVOS, mesa: Optional[str] = None, somente_hoje: bool = True) -> list:
        with self.lock:
            sql = f"SELECT id FROM pedidos WHERE tipo = 'pedido' AND status IN ({','.join('?' * len(statuses))})"
            params = list(statuses)
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
                "SELECT id, codigo, cliente, mesa, status, chamada_seq, chamado_em FROM pedidos "
                "WHERE tipo = 'pedido' AND chamada_seq IS NOT NULL AND status IN ('chamado', 'entregue') AND dia = ? "
                "ORDER BY chamada_seq DESC LIMIT ?",
                (self._dia(), max(1, min(int(limite), 50))),
            ).fetchall()
            return [dict(l) for l in linhas]

    def contas_abertas(self) -> list:
        """Pedidos ainda não pagos (de qualquer dia), agrupados por mesa —
        ou um por um, quando não têm mesa (balcão)."""
        with self.lock:
            ids = [l["id"] for l in self.conn.execute(
                "SELECT id FROM pedidos WHERE tipo = 'pedido' AND status != 'cancelado' AND recebimento_id IS NULL "
                "ORDER BY criado_em, id")]
        grupos = {}
        for pedido in (self.obter_pedido(i) for i in ids):
            if pedido["mesa"]:
                chave, titulo = "mesa:" + pedido["mesa"], "Mesa " + pedido["mesa"]
            else:
                chave = f"pedido:{pedido['id']}"
                titulo = f"Pedido nº {pedido['codigo']}" + (f" · {pedido['cliente']}" if pedido["cliente"] else "")
            grupo = grupos.setdefault(chave, {"chave": chave, "titulo": titulo, "pedidos": [], "total": 0})
            grupo["pedidos"].append(pedido)
            grupo["total"] += pedido["total_centavos"]
        return list(grupos.values())

    # --- Caixa ----------------------------------------------------------------

    def sessao_aberta(self) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM sessoes_caixa WHERE fechado_em IS NULL ORDER BY id DESC LIMIT 1").fetchone()
            return dict(linha) if linha else None

    def _exigir_sessao(self) -> dict:
        sessao = self.sessao_aberta()
        if not sessao:
            raise ErroNegocio("O caixa está fechado. Abra o caixa primeiro.")
        return sessao

    def abrir_caixa(self, valor_abertura, por: dict) -> dict:
        valor = _centavos(valor_abertura, "valor de abertura")
        with self._transacao():
            if self.sessao_aberta():
                raise ErroNegocio("O caixa já está aberto.")
            cur = self.conn.execute(
                "INSERT INTO sessoes_caixa (aberto_por, aberto_por_nome, aberto_em, valor_abertura) VALUES (?, ?, ?, ?)",
                (por["id"], por["nome"], self.agora(), valor),
            )
            self._registrar(por, "Abriu o caixa", f"Fundo de troco: {moeda(valor)}")
        return self.resumo_sessao(cur.lastrowid)

    def movimentar_caixa(self, tipo: str, valor, motivo: str, por: dict) -> dict:
        if tipo not in ("sangria", "suprimento"):
            raise ErroNegocio("Movimento inválido.")
        valor = _centavos(valor, "valor", permitir_zero=False)
        motivo = _texto(motivo, 200)
        if not motivo:
            raise ErroNegocio("Informe o motivo.")
        sessao = self._exigir_sessao()
        if tipo == "sangria":
            disponivel = self.resumo_sessao(sessao["id"])["esperado_dinheiro"]
            if valor > disponivel:
                raise ErroNegocio(f"Sangria maior que o dinheiro em caixa ({moeda(disponivel)}).")
        with self._transacao():
            self.conn.execute(
                "INSERT INTO movimentos_caixa (sessao_id, tipo, valor, motivo, usuario_id, usuario_nome, criado_em) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sessao["id"], tipo, valor, motivo, por["id"], por["nome"], self.agora()),
            )
            self._registrar(por, "Fez sangria" if tipo == "sangria" else "Fez suprimento", f"{moeda(valor)} — {motivo}")
        return self.resumo_sessao(sessao["id"])

    def receber(self, pedido_ids: list, formas: list, por: dict, desconto=0, acrescimo=0) -> dict:
        """Registra o pagamento de um ou mais pedidos (ex.: a conta inteira
        da mesa), podendo dividir entre várias formas. Se entrar mais
        dinheiro do que o devido, a sobra é o troco."""
        sessao = self._exigir_sessao()
        if not isinstance(pedido_ids, list) or not pedido_ids:
            raise ErroNegocio("Selecione o que vai ser pago.")
        pedidos = []
        for pid in dict.fromkeys(pedido_ids):
            try:
                pedido = self._exigir_pedido(int(pid))
            except (TypeError, ValueError):
                raise ErroNegocio("Pedido inválido.")
            if pedido["status"] == "cancelado":
                raise ErroNegocio(f"O pedido nº {pedido['codigo']} foi cancelado.")
            if pedido["pago"]:
                raise ErroNegocio(f"O pedido nº {pedido['codigo']} já foi pago.")
            pedidos.append(pedido)
        subtotal = sum(p["total_centavos"] for p in pedidos)
        desconto = _centavos(desconto, "desconto")
        acrescimo = _centavos(acrescimo, "acréscimo")
        if desconto > subtotal:
            raise ErroNegocio("O desconto é maior que o valor da conta.")
        total = subtotal - desconto + acrescimo

        valores = {}
        if not isinstance(formas, list):
            raise ErroNegocio("Formas de pagamento inválidas.")
        for f in formas:
            forma = (f or {}).get("forma")
            if forma not in FORMAS_PAGAMENTO:
                raise ErroNegocio("Forma de pagamento inválida.")
            valor = _centavos(f.get("valor"), FORMAS_PAGAMENTO[forma])
            if valor:
                valores[forma] = valores.get(forma, 0) + valor
        pago = sum(valores.values())
        if pago < total:
            raise ErroNegocio(f"Falta receber {moeda(total - pago)}.")
        troco = pago - total
        if troco > valores.get("dinheiro", 0):
            raise ErroNegocio("O valor recebido em cartão/pix/vale passa do total da conta. Só dinheiro pode ter troco.")
        if troco:
            valores["dinheiro"] -= troco
            if not valores["dinheiro"]:
                del valores["dinheiro"]

        mesas = sorted({p["mesa"] for p in pedidos if p["mesa"]})
        codigos = ", ".join(p["codigo"] for p in pedidos)
        descricao = (f"Mesa {', '.join(mesas)} — " if mesas else "") + f"pedido(s) {codigos}"
        with self._transacao():
            cur = self.conn.execute(
                "INSERT INTO recebimentos (sessao_id, usuario_id, usuario_nome, descricao, subtotal, desconto, "
                "acrescimo, total, troco, criado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sessao["id"], por["id"], por["nome"], descricao, subtotal, desconto, acrescimo, total, troco, self.agora()),
            )
            rid = cur.lastrowid
            for forma, valor in valores.items():
                self.conn.execute("INSERT INTO recebimento_formas (recebimento_id, forma, valor) VALUES (?, ?, ?)",
                                  (rid, forma, valor))
            for p in pedidos:
                atualizado = self.conn.execute(
                    "UPDATE pedidos SET recebimento_id = ? WHERE id = ? AND recebimento_id IS NULL", (rid, p["id"]))
                if atualizado.rowcount != 1:  # outro caixa recebeu no mesmo instante
                    raise ErroNegocio(f"O pedido nº {p['codigo']} já foi pago.")
            detalhes = (f"{descricao}: {moeda(total)} em "
                        + ", ".join(f"{FORMAS_PAGAMENTO[f]} {moeda(v)}" for f, v in valores.items())
                        + (f"; desconto {moeda(desconto)}" if desconto else "")
                        + (f"; acréscimo {moeda(acrescimo)}" if acrescimo else "")
                        + (f"; troco {moeda(troco)}" if troco else ""))
            self._registrar(por, "Recebeu pagamento", detalhes)
        return self.obter_recebimento(rid)

    def obter_recebimento(self, rid: int) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM recebimentos WHERE id = ?", (rid,)).fetchone()
            if not linha:
                return None
            rec = dict(linha)
            rec["formas"] = [dict(f) for f in self.conn.execute(
                "SELECT forma, valor FROM recebimento_formas WHERE recebimento_id = ? ORDER BY id", (rid,))]
            rec["pedidos"] = [l["codigo"] for l in self.conn.execute(
                "SELECT codigo FROM pedidos WHERE recebimento_id = ? ORDER BY id", (rid,))]
            return rec

    def listar_recebimentos(self, sessao_id: int) -> list:
        with self.lock:
            ids = [l["id"] for l in self.conn.execute(
                "SELECT id FROM recebimentos WHERE sessao_id = ? ORDER BY id DESC", (sessao_id,))]
        return [self.obter_recebimento(i) for i in ids]

    def estornar_recebimento(self, rid: int, motivo: str, por: dict) -> None:
        rec = self.obter_recebimento(rid)
        if not rec:
            raise ErroNegocio("Pagamento não encontrado.")
        if rec["estornado_em"]:
            raise ErroNegocio("Esse pagamento já foi estornado.")
        sessao = self.sessao_aberta()
        if not sessao or sessao["id"] != rec["sessao_id"]:
            raise ErroNegocio("Só dá para estornar pagamentos do caixa que está aberto agora.")
        motivo = _texto(motivo, 200)
        if not motivo:
            raise ErroNegocio("Informe o motivo do estorno.")
        with self._transacao():
            self.conn.execute(
                "UPDATE recebimentos SET estornado_em = ?, estornado_por_nome = ?, motivo_estorno = ? WHERE id = ?",
                (self.agora(), por["nome"], motivo, rid),
            )
            # Os pedidos voltam a ficar "a receber".
            self.conn.execute("UPDATE pedidos SET recebimento_id = NULL WHERE recebimento_id = ?", (rid,))
            self._registrar(por, "Estornou pagamento", f"{rec['descricao']}: {moeda(rec['total'])} — motivo: {motivo}")

    def resumo_sessao(self, sessao_id: int) -> dict:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM sessoes_caixa WHERE id = ?", (sessao_id,)).fetchone()
            if not linha:
                raise ErroNegocio("Caixa não encontrado.")
            s = dict(linha)
            por_forma = {f: 0 for f in FORMAS_PAGAMENTO}
            for l in self.conn.execute(
                "SELECT f.forma, SUM(f.valor) AS v FROM recebimento_formas f JOIN recebimentos r ON r.id = f.recebimento_id "
                "WHERE r.sessao_id = ? AND r.estornado_em IS NULL GROUP BY f.forma", (sessao_id,)
            ):
                por_forma[l["forma"]] = l["v"]
            vendas = self.conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total, COALESCE(SUM(desconto), 0) AS desc, "
                "COALESCE(SUM(acrescimo), 0) AS acr, COALESCE(SUM(troco), 0) AS troco "
                "FROM recebimentos WHERE sessao_id = ? AND estornado_em IS NULL", (sessao_id,)
            ).fetchone()
            estornos = self.conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total FROM recebimentos "
                "WHERE sessao_id = ? AND estornado_em IS NOT NULL", (sessao_id,)
            ).fetchone()
            movimentos = [dict(m) for m in self.conn.execute(
                "SELECT tipo, valor, motivo, usuario_nome, criado_em FROM movimentos_caixa WHERE sessao_id = ? ORDER BY id",
                (sessao_id,))]
        sangrias = sum(m["valor"] for m in movimentos if m["tipo"] == "sangria")
        suprimentos = sum(m["valor"] for m in movimentos if m["tipo"] == "suprimento")
        esperado = s["valor_abertura"] + por_forma["dinheiro"] + suprimentos - sangrias
        s.update({
            "aberto": s["fechado_em"] is None,
            "por_forma": por_forma,
            "qtd_vendas": vendas["n"],
            "total_vendas": vendas["total"],
            "descontos": vendas["desc"],
            "acrescimos": vendas["acr"],
            "troco": vendas["troco"],
            "qtd_estornos": estornos["n"],
            "total_estornos": estornos["total"],
            "movimentos": movimentos,
            "sangrias": sangrias,
            "suprimentos": suprimentos,
            # Enquanto aberto, é calculado na hora; depois de fechado, vale o
            # que foi gravado no fechamento.
            "esperado_dinheiro": esperado if s["fechado_em"] is None else s["esperado_dinheiro"],
        })
        return s

    def fechar_caixa(self, valor_contado, observacao: str, por: dict) -> dict:
        sessao = self._exigir_sessao()
        contado = _centavos(valor_contado, "valor contado")
        resumo = self.resumo_sessao(sessao["id"])
        esperado = resumo["esperado_dinheiro"]
        diferenca = contado - esperado
        with self._transacao():
            self.conn.execute(
                "UPDATE sessoes_caixa SET fechado_por = ?, fechado_por_nome = ?, fechado_em = ?, valor_contado = ?, "
                "esperado_dinheiro = ?, diferenca = ?, observacao = ? WHERE id = ? AND fechado_em IS NULL",
                (por["id"], por["nome"], self.agora(), contado, esperado, diferenca, _texto(observacao, 300), sessao["id"]),
            )
            situacao = "sem diferença" if diferenca == 0 else (f"SOBRA de {moeda(diferenca)}" if diferenca > 0 else f"FALTA de {moeda(-diferenca)}")
            self._registrar(por, "Fechou o caixa",
                            f"Vendas {moeda(resumo['total_vendas'])}; dinheiro esperado {moeda(esperado)}, "
                            f"contado {moeda(contado)} — {situacao}")
        return self.resumo_sessao(sessao["id"])

    # --- Relatórios ----------------------------------------------------------

    @staticmethod
    def _periodo(de: str, ate: str):
        try:
            inicio = datetime.strptime(de, "%Y-%m-%d")
            fim = datetime.strptime(ate, "%Y-%m-%d") + timedelta(days=1)
        except (TypeError, ValueError):
            raise ErroNegocio("Período inválido.")
        if fim <= inicio:
            raise ErroNegocio("A data final é anterior à inicial.")
        return inicio.timestamp(), fim.timestamp()

    def relatorio(self, de: str, ate: str) -> dict:
        ini, fim = self._periodo(de, ate)
        with self.lock:
            filtro = "r.criado_em >= ? AND r.criado_em < ? AND r.estornado_em IS NULL"
            geral = self.conn.execute(
                f"SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total, COALESCE(SUM(subtotal), 0) AS bruto, "
                f"COALESCE(SUM(desconto), 0) AS desc, COALESCE(SUM(acrescimo), 0) AS acr FROM recebimentos r WHERE {filtro}",
                (ini, fim)).fetchone()
            por_forma = {f: 0 for f in FORMAS_PAGAMENTO}
            for l in self.conn.execute(
                f"SELECT f.forma, SUM(f.valor) AS v FROM recebimento_formas f JOIN recebimentos r ON r.id = f.recebimento_id "
                f"WHERE {filtro} GROUP BY f.forma", (ini, fim)):
                por_forma[l["forma"]] = l["v"]
            por_produto = [dict(l) for l in self.conn.execute(
                f"SELECT i.nome, SUM(i.quantidade) AS quantidade, SUM(i.quantidade * i.preco_centavos) AS valor "
                f"FROM pedido_itens i JOIN pedidos p ON p.id = i.pedido_id JOIN recebimentos r ON r.id = p.recebimento_id "
                f"WHERE {filtro} GROUP BY i.nome ORDER BY valor DESC", (ini, fim))]
            por_usuario = [dict(l) for l in self.conn.execute(
                f"SELECT r.usuario_nome AS nome, COUNT(*) AS quantidade, SUM(r.total) AS valor FROM recebimentos r "
                f"WHERE {filtro} GROUP BY r.usuario_nome ORDER BY valor DESC", (ini, fim))]
            por_dia = {}
            for l in self.conn.execute(f"SELECT criado_em, total FROM recebimentos r WHERE {filtro}", (ini, fim)):
                dia = self._dia(l["criado_em"])
                por_dia[dia] = por_dia.get(dia, 0) + l["total"]
            estornos = [dict(l) for l in self.conn.execute(
                "SELECT descricao, total, usuario_nome, estornado_por_nome, motivo_estorno, estornado_em FROM recebimentos "
                "WHERE estornado_em >= ? AND estornado_em < ? ORDER BY estornado_em", (ini, fim))]
            cancelados = [dict(l) for l in self.conn.execute(
                "SELECT codigo, mesa, total_centavos, cancelado_por_nome, motivo_cancelamento, atualizado_em FROM pedidos "
                "WHERE status = 'cancelado' AND atualizado_em >= ? AND atualizado_em < ? ORDER BY atualizado_em", (ini, fim))]
            sessoes_ids = [l["id"] for l in self.conn.execute(
                "SELECT id FROM sessoes_caixa WHERE aberto_em >= ? AND aberto_em < ? ORDER BY id", (ini, fim))]
            pendentes = self.conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(total_centavos), 0) AS total FROM pedidos "
                "WHERE tipo = 'pedido' AND status != 'cancelado' AND recebimento_id IS NULL").fetchone()
        return {
            "de": de, "ate": ate,
            "qtd_vendas": geral["n"],
            "total_vendas": geral["total"],
            "total_bruto": geral["bruto"],
            "descontos": geral["desc"],
            "acrescimos": geral["acr"],
            "ticket_medio": geral["total"] // geral["n"] if geral["n"] else 0,
            "por_forma": por_forma,
            "por_produto": por_produto,
            "por_usuario": por_usuario,
            "por_dia": [{"dia": d, "valor": v} for d, v in sorted(por_dia.items())],
            "estornos": estornos,
            "cancelados": cancelados,
            "sessoes": [self.resumo_sessao(i) for i in sessoes_ids],
            "a_receber": {"quantidade": pendentes["n"], "total": pendentes["total"]},
        }

    def vendas_csv(self, de: str, ate: str) -> str:
        """Planilha das vendas do período (abre no Excel), pra contabilidade."""
        ini, fim = self._periodo(de, ate)
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";")
        w.writerow(["Data", "Hora", "Caixa (sessão)", "Atendente", "Descrição", "Subtotal", "Desconto", "Acréscimo",
                    "Total", *FORMAS_PAGAMENTO.values(), "Troco", "Situação"])
        with self.lock:
            ids = [l["id"] for l in self.conn.execute(
                "SELECT id FROM recebimentos WHERE criado_em >= ? AND criado_em < ? ORDER BY criado_em", (ini, fim))]
        reais = lambda c: f"{c / 100:.2f}".replace(".", ",")
        for rec in (self.obter_recebimento(i) for i in ids):
            quando = datetime.fromtimestamp(rec["criado_em"])
            formas = {f["forma"]: f["valor"] for f in rec["formas"]}
            w.writerow([quando.strftime("%d/%m/%Y"), quando.strftime("%H:%M"), rec["sessao_id"], rec["usuario_nome"],
                        rec["descricao"], reais(rec["subtotal"]), reais(rec["desconto"]), reais(rec["acrescimo"]),
                        reais(rec["total"]), *(reais(formas.get(f, 0)) for f in FORMAS_PAGAMENTO), reais(rec["troco"]),
                        f"Estornado ({rec['motivo_estorno']})" if rec["estornado_em"] else "OK"])
        # BOM: o Excel brasileiro só reconhece os acentos com ele.
        return "﻿" + saida.getvalue()

    def listar_auditoria(self, de: str, ate: str, usuario_id: Optional[int] = None, busca: str = "", limite: int = 1000) -> list:
        ini, fim = self._periodo(de, ate)
        sql = "SELECT * FROM auditoria WHERE criado_em >= ? AND criado_em < ?"
        params = [ini, fim]
        if usuario_id:
            sql += " AND usuario_id = ?"
            params.append(int(usuario_id))
        if busca:
            sql += " AND (acao LIKE ? OR detalhes LIKE ? OR usuario_nome LIKE ?)"
            params += [f"%{busca}%"] * 3
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limite), 5000)))
        with self.lock:
            return [dict(l) for l in self.conn.execute(sql, params)]

    # --- Chamados de garçom ----------------------------------------------

    def chamar_garcom(self, mesa: str, tipo: str = "garcom") -> dict:
        if tipo not in ("garcom", "conta"):
            raise ErroNegocio("Tipo de chamado inválido.")
        with self.lock:
            # Cliente apertando o botão várias vezes não gera vários chamados.
            existente = self.conn.execute(
                "SELECT * FROM chamados_garcom WHERE mesa = ? AND tipo = ? AND atendido_em IS NULL", (mesa, tipo),
            ).fetchone()
            if existente:
                return dict(existente)
            with self._transacao():
                cur = self.conn.execute("INSERT INTO chamados_garcom (mesa, tipo, criado_em) VALUES (?, ?, ?)",
                                        (mesa, tipo, self.agora()))
                self._registrar({"id": None, "nome": f"Cliente (mesa {mesa})"},
                                "Pediu a conta" if tipo == "conta" else "Chamou o garçom")
            return dict(self.conn.execute("SELECT * FROM chamados_garcom WHERE id = ?", (cur.lastrowid,)).fetchone())

    def chamados_pendentes(self, mesa: Optional[str] = None) -> list:
        with self.lock:
            sql = "SELECT * FROM chamados_garcom WHERE atendido_em IS NULL"
            params = []
            if mesa is not None:
                sql += " AND mesa = ?"
                params.append(mesa)
            return [dict(l) for l in self.conn.execute(sql + " ORDER BY criado_em", params)]

    def atender_chamado(self, chamado_id: int, por: Optional[dict] = None) -> None:
        with self.lock:
            chamado = self.conn.execute("SELECT * FROM chamados_garcom WHERE id = ? AND atendido_em IS NULL",
                                        (chamado_id,)).fetchone()
            if not chamado:
                return
            with self._transacao():
                self.conn.execute("UPDATE chamados_garcom SET atendido_em = ? WHERE id = ?", (self.agora(), chamado_id))
                tipo = "pedido de conta" if chamado["tipo"] == "conta" else "chamado de garçom"
                self._registrar(por, "Atendeu chamado", f"{tipo} da mesa {chamado['mesa']}")

    # --- Mídias do painel ---------------------------------------------

    def listar_midias(self, somente_ativas: bool = False) -> list:
        with self.lock:
            sql = "SELECT * FROM midias"
            if somente_ativas:
                sql += " WHERE ativo = 1"
            linhas = self.conn.execute(sql + " ORDER BY ordem, id").fetchall()
            return [{**dict(l), "ativo": bool(l["ativo"])} for l in linhas]

    def adicionar_midia(self, arquivo: str, tipo: str, nome_original: str = "", por: Optional[dict] = None) -> dict:
        with self._transacao():
            linha = self.conn.execute("SELECT MAX(ordem) AS o FROM midias").fetchone()
            cur = self.conn.execute(
                "INSERT INTO midias (arquivo, nome_original, tipo, ordem) VALUES (?, ?, ?, ?)",
                (arquivo, nome_original[:200], tipo, (linha["o"] or 0) + 1),
            )
            self._registrar(por, "Enviou mídia para o painel", f"{tipo}: {nome_original}")
        return dict(self.conn.execute("SELECT * FROM midias WHERE id = ?", (cur.lastrowid,)).fetchone())

    def atualizar_midia(self, midia_id: int, dados: dict, por: Optional[dict] = None) -> None:
        with self._transacao():
            if "ativo" in dados:
                self.conn.execute("UPDATE midias SET ativo = ? WHERE id = ?", (1 if dados["ativo"] else 0, midia_id))
            if "duracao" in dados:
                duracao = dados["duracao"]
                duracao = int(duracao) if duracao not in (None, "", 0) else None
                self.conn.execute("UPDATE midias SET duracao = ? WHERE id = ?", (duracao, midia_id))
            self._registrar(por, "Alterou mídia do painel", json.dumps(dados, ensure_ascii=False))

    def mover_midia(self, midia_id: int, direcao: int, por: Optional[dict] = None) -> None:
        ids = [m["id"] for m in self.listar_midias()]
        if midia_id not in ids:
            raise ErroNegocio("Mídia não encontrada.")
        i = ids.index(midia_id)
        j = i + (1 if direcao > 0 else -1)
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        with self._transacao():
            for ordem, mid in enumerate(ids, start=1):
                self.conn.execute("UPDATE midias SET ordem = ? WHERE id = ?", (ordem, mid))

    def excluir_midia(self, midia_id: int, por: Optional[dict] = None) -> Optional[str]:
        with self.lock:
            linha = self.conn.execute("SELECT arquivo, nome_original FROM midias WHERE id = ?", (midia_id,)).fetchone()
        if not linha:
            return None
        with self._transacao():
            self.conn.execute("DELETE FROM midias WHERE id = ?", (midia_id,))
            self._registrar(por, "Excluiu mídia do painel", linha["nome_original"])
        return linha["arquivo"]
