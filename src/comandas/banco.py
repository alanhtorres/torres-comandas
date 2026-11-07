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
    # Cada impressora é "rede" (IP e porta) ou "usb" (instalada no Windows
    # deste PC, escolhida pelo nome).
    "impressora_cozinha_ativa": False,
    "impressora_cozinha_tipo": "rede",
    "impressora_cozinha_host": "",
    "impressora_cozinha_porta": 9100,
    "impressora_cozinha_usb": "",
    # Impressora do bar: os produtos com destino "bar" (bebidas, drinks...).
    "impressora_bar_ativa": False,
    "impressora_bar_tipo": "rede",
    "impressora_bar_host": "",
    "impressora_bar_porta": 9100,
    "impressora_bar_usb": "",
    # Impressora do caixa: conferência de conta e fechamento de caixa.
    "impressora_caixa_ativa": False,
    "impressora_caixa_tipo": "rede",
    "impressora_caixa_host": "",
    "impressora_caixa_porta": 9100,
    "impressora_caixa_usb": "",
    # 48 colunas = bobina de 80 mm; 32 colunas = bobina de 58 mm.
    "impressora_colunas": 48,
    "impressora_codificacao": "cp850",
    # Modo comanda: cada cliente que entra recebe uma comanda (cartão),
    # aberta com cadastro (nome e telefone obrigatórios).
    "modo_comandas_ativo": False,
    # DDD usado quando o telefone é digitado sem ele (ex.: "11"). Vazio = exige DDD.
    "ddd_padrao": "",
    # Como abrir o WhatsApp para enviar: "web" (WhatsApp Web no navegador),
    # "app" (aplicativo instalado no PC) ou "link" (wa.me — bom no celular).
    "whatsapp_abrir_em": "web",
    "msg_aniversario": ("Olá, {nome}! 🎉 A equipe do {loja} deseja um feliz aniversário! "
                        "Venha comemorar com a gente — temos uma surpresa para você."),
}

# Chaves que nunca saem pela API de configuração.
CONFIG_PRIVADA = {"secret_key", "versao_permissoes"}

# O que cada usuário pode acessar — o administrador marca uma a uma.
PERMISSOES = {
    "pedidos": "Caixa: lançar e acompanhar pedidos, chamar no painel, atender garçom",
    "garcom": "Página do garçom: pedidos na mesa pelo celular/tablet e alertas do QR code",
    "cozinha": "Tela da cozinha (iniciar preparo / pronto)",
    "receber": "Receber pagamentos",
    "caixa": "Abrir e fechar o caixa, sangria e suprimento",
    "cancelar": "Cancelar pedidos (com motivo)",
    "estornar": "Estornar pagamentos já recebidos (aba Recebidos)",
    "comandas": "Comandas: abrir comanda e cadastrar cliente na entrada",
    "clientes": "Clientes: lista completa (CPF, aniversários), exportar e mensagens de WhatsApp",
    "cardapio": "Cadastro de produtos (cardápio)",
    "mesas": "Mesas e QR codes",
    "midias": "Fotos e vídeos do painel",
    "configuracoes": "Configurações do sistema e impressoras",
    "relatorios": "Relatórios financeiros e de vendas",
    "historico": "Histórico de ações dos usuários",
    "usuarios": "Usuários e permissões",
}
# Permissões criadas depois da 2.0.0: quem já administrava usuários recebe
# automaticamente, pra não perder nenhum acesso que tinha (o estorno antes
# vinha junto com "cancelar").
PERMISSOES_NOVAS = {2: ["garcom", "estornar"], 3: ["comandas", "clientes"]}

ORIGENS = {"caixa": "Caixa", "qrcode": "QR code", "garcom": "Garçom"}

# Permissões que dão acesso à tela de administração.
PERMISSOES_ADMIN = ("cardapio", "mesas", "midias", "clientes", "configuracoes", "relatorios", "historico", "usuarios")

# Modelos prontos para preencher as permissões de um usuário novo.
MODELOS = {
    "admin": ("Administrador", list(PERMISSOES)),
    "caixa": ("Caixa", ["pedidos", "cozinha", "receber", "caixa", "comandas"]),
    "garcom": ("Garçom", ["garcom"]),
    "entrada": ("Entrada / recepção", ["comandas"]),
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
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    telefone TEXT NOT NULL,             -- só dígitos, com DDD (ex.: 11987654321)
    cpf TEXT,                           -- só dígitos (opcional)
    nascimento TEXT,                    -- AAAA-MM-DD (opcional)
    aceita_mensagens INTEGER NOT NULL DEFAULT 0,
    consentimento_em REAL,
    observacao TEXT NOT NULL DEFAULT '',
    criado_em REAL NOT NULL,
    atualizado_em REAL NOT NULL,
    removido_em REAL                    -- dados apagados a pedido do cliente (LGPD)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_telefone ON clientes(telefone) WHERE removido_em IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_cpf ON clientes(cpf) WHERE cpf IS NOT NULL AND removido_em IS NULL;
CREATE TABLE IF NOT EXISTS comandas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT NOT NULL,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    cliente_nome TEXT NOT NULL,
    aberta_em REAL NOT NULL,
    aberta_por_nome TEXT NOT NULL,
    fechada_em REAL,
    fechada_por_nome TEXT NOT NULL DEFAULT '',
    motivo_fechamento TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_comandas_abertas ON comandas(fechada_em);
CREATE TABLE IF NOT EXISTS mensagens_enviadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    campanha TEXT NOT NULL,
    texto TEXT NOT NULL,
    usuario_nome TEXT NOT NULL,
    enviado_em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mensagens_campanha ON mensagens_enviadas(campanha, cliente_id);
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
    "produtos": {
        # Produto que precisa de preparo: aparece na cozinha e sai na
        # impressora dela. Bebidas em lata, chips etc. vão direto do caixa.
        "vai_cozinha": "INTEGER NOT NULL DEFAULT 1",
        # Onde o produto sai: "cozinha", "bar" ou "nenhum" (vazio = bancos
        # de antes do bar, que seguem o vai_cozinha). Ver setor_do_item().
        "destino": "TEXT NOT NULL DEFAULT ''",
    },
    "pedido_itens": {
        "vai_cozinha": "INTEGER NOT NULL DEFAULT 1",
        "setor": "TEXT NOT NULL DEFAULT ''",
    },
    "pedidos": {
        "usuario_id": "INTEGER",
        "usuario_nome": "TEXT NOT NULL DEFAULT ''",
        "recebimento_id": "INTEGER",
        "cancelado_por_nome": "TEXT NOT NULL DEFAULT ''",
        "comanda_id": "INTEGER",
        "motivo_cancelamento": "TEXT NOT NULL DEFAULT ''",
    },
}


class ErroNegocio(Exception):
    """Erro de regra de negócio, com mensagem pronta pra mostrar ao usuário."""


# Onde cada produto sai: na cozinha (tela e impressora da cozinha), no bar
# (impressora do bar) ou em nenhum lugar (já pronto: sai direto do caixa).
DESTINOS = {"cozinha": "Cozinha", "bar": "Bar", "nenhum": "Não imprime (já pronto)"}


def setor_do_item(item: dict) -> str:
    """Destino de um produto ou item de pedido. Os gravados antes do bar
    existir não têm destino e seguem o "vai para a cozinha"."""
    destino = item.get("destino") or item.get("setor")
    if destino in DESTINOS:
        return destino
    return "cozinha" if item.get("vai_cozinha", True) else "nenhum"


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


def _digitos(valor) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def normalizar_telefone(valor, ddd_padrao: str = "") -> str:
    """Telefone brasileiro só com dígitos e DDD (10 ou 11 dígitos).
    Aceita com máscara, com +55 e, se houver DDD padrão, sem DDD."""
    tel = _digitos(valor).lstrip("0")
    if tel.startswith("55") and len(tel) in (12, 13):
        tel = tel[2:]
    if len(tel) in (8, 9) and ddd_padrao:
        tel = _digitos(ddd_padrao) + tel
    # DDD não tem zero; celular tem 9 dígitos começando com 9; fixo, 8
    # dígitos começando de 2 a 5.
    valido = (len(tel) in (10, 11) and "0" not in tel[:2]
              and ((len(tel) == 11 and tel[2] == "9") or (len(tel) == 10 and tel[2] in "2345")))
    if not valido:
        raise ErroNegocio("Telefone inválido. Informe com DDD, ex.: (11) 98765-4321.")
    return tel


def formatar_telefone(tel: str) -> str:
    if len(tel) == 11:
        return f"({tel[:2]}) {tel[2:7]}-{tel[7:]}"
    if len(tel) == 10:
        return f"({tel[:2]}) {tel[2:6]}-{tel[6:]}"
    return tel


def validar_cpf(valor) -> Optional[str]:
    """CPF só com dígitos (ou None se vazio). Confere os dígitos verificadores."""
    cpf = _digitos(valor)
    if not cpf:
        return None
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        raise ErroNegocio("CPF inválido.")
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11 % 10
        if digito != int(cpf[tamanho]):
            raise ErroNegocio("CPF inválido.")
    return cpf


def formatar_cpf(cpf: Optional[str]) -> str:
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if cpf and len(cpf) == 11 else ""


def validar_nascimento(valor, hoje: datetime) -> Optional[str]:
    """Data de nascimento em AAAA-MM-DD (aceita também DD/MM/AAAA)."""
    texto = str(valor or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            data = datetime.strptime(texto, formato)
            break
        except ValueError:
            continue
    else:
        raise ErroNegocio("Data de nascimento inválida. Use DD/MM/AAAA.")
    if data.year < 1900 or data > hoje:
        raise ErroNegocio("Data de nascimento inválida.")
    return data.strftime("%Y-%m-%d")


def proximo_aniversario(nascimento: str, hoje: datetime):
    """(data do próximo aniversário, idade que vai fazer). 29/02 vira 28/02
    nos anos que não são bissextos."""
    nasc = datetime.strptime(nascimento, "%Y-%m-%d")
    hoje = hoje.replace(hour=0, minute=0, second=0, microsecond=0)
    for ano in (hoje.year, hoje.year + 1):
        try:
            data = nasc.replace(year=ano)
        except ValueError:
            data = nasc.replace(year=ano, day=28)
        if data >= hoje:
            return data, ano - nasc.year
    return data, ano - nasc.year


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
        linha = self.conn.execute("SELECT valor FROM config WHERE chave = 'versao_permissoes'").fetchone()
        versao = json.loads(linha["valor"]) if linha else 1
        for alvo, novas in sorted(PERMISSOES_NOVAS.items()):
            if versao >= alvo:
                continue
            for u in self.conn.execute("SELECT id, permissoes FROM usuarios").fetchall():
                perms = json.loads(u["permissoes"])
                if "usuarios" in perms:
                    perms += [p for p in novas if p not in perms]
                    self.conn.execute("UPDATE usuarios SET permissoes = ? WHERE id = ?", (json.dumps(perms), u["id"]))
            versao = alvo
        self.conn.execute(
            "INSERT INTO config (chave, valor) VALUES ('versao_permissoes', ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (json.dumps(versao),))

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
                if chave.startswith("impressora_") and chave.endswith("_tipo") and valor not in ("rede", "usb"):
                    raise ErroNegocio("Tipo de impressora inválido (rede ou USB).")
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
        dados["vai_cozinha"] = bool(dados["vai_cozinha"])
        dados["destino"] = setor_do_item(dados)
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
        if dados.get("destino") and dados["destino"] not in DESTINOS:
            raise ErroNegocio("Destino do produto inválido.")
        destino = setor_do_item({"destino": dados.get("destino"), "vai_cozinha": dados.get("vai_cozinha", True)})
        return {
            "nome": nome,
            "descricao": _texto(dados.get("descricao"), 200),
            "categoria": _texto(dados.get("categoria"), 40) or "Geral",
            "preco_centavos": _centavos(dados.get("preco_centavos", 0), "preço"),
            "ativo": 1 if dados.get("ativo", True) else 0,
            "vai_cozinha": 1 if destino == "cozinha" else 0,
            "destino": destino,
            "ordem": int(dados.get("ordem") or 0),
        }

    def criar_produto(self, dados: dict, por: Optional[dict] = None) -> dict:
        valores = self._validar_produto(dados)
        with self._transacao():
            cur = self.conn.execute(
                "INSERT INTO produtos (nome, descricao, categoria, preco_centavos, ativo, vai_cozinha, destino, ordem) "
                "VALUES (:nome, :descricao, :categoria, :preco_centavos, :ativo, :vai_cozinha, :destino, :ordem)",
                valores,
            )
            self._registrar(por, "Cadastrou produto", f"{valores['nome']} — {moeda(valores['preco_centavos'])}"
                            + {"cozinha": "", "bar": " (sai no bar)", "nenhum": " (não vai para a cozinha)"}[valores["destino"]])
        return self.obter_produto(cur.lastrowid)

    def atualizar_produto(self, produto_id: int, dados: dict, por: Optional[dict] = None) -> dict:
        atual = self.obter_produto(produto_id)
        if not atual:
            raise ErroNegocio("Produto não encontrado.")
        dados = dict(dados)
        if "vai_cozinha" in dados and "destino" not in dados:
            # Botão antigo "Pôr/Tirar da cozinha".
            dados["destino"] = "cozinha" if dados["vai_cozinha"] else "nenhum"
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
        if valores["destino"] != atual["destino"]:
            mudancas.append(f"sai em: {DESTINOS[atual['destino']]} → {DESTINOS[valores['destino']]}")
        with self._transacao():
            self.conn.execute(
                "UPDATE produtos SET nome = :nome, descricao = :descricao, categoria = :categoria, "
                "preco_centavos = :preco_centavos, ativo = :ativo, vai_cozinha = :vai_cozinha, destino = :destino, "
                "ordem = :ordem WHERE id = :id",
                valores,
            )
            if mudancas:
                self._registrar(por, "Alterou produto", f"{atual['nome']}: " + "; ".join(mudancas))
        return self.obter_produto(produto_id)

    def definir_destino_categoria(self, categoria: str, destino: str, por: Optional[dict] = None) -> int:
        """Escolhe de uma vez onde saem todos os produtos da categoria
        (ex.: "Bebidas" → bar, "Lanches" → cozinha)."""
        if destino not in DESTINOS:
            raise ErroNegocio("Destino inválido.")
        with self._transacao():
            cur = self.conn.execute("UPDATE produtos SET destino = ?, vai_cozinha = ? WHERE categoria = ?",
                                    (destino, 1 if destino == "cozinha" else 0, categoria))
            self._registrar(por, "Alterou categoria", f"{categoria}: todos os produtos saem em {DESTINOS[destino]}")
        return cur.rowcount

    def definir_cozinha_categoria(self, categoria: str, vai_cozinha: bool, por: Optional[dict] = None) -> int:
        return self.definir_destino_categoria(categoria, "cozinha" if vai_cozinha else "nenhum", por=por)

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
                     cliente: str = "", observacao: str = "", por: Optional[dict] = None,
                     comanda_id: Optional[int] = None) -> dict:
        if not isinstance(itens, list) or not itens:
            raise ErroNegocio("O pedido está vazio.")
        if origem not in ORIGENS:
            raise ErroNegocio("Origem do pedido inválida.")
        comanda = None
        if comanda_id:
            comanda = self._exigir_comanda_aberta(comanda_id)
            # Nome que aparece no painel: o primeiro nome do dono da comanda.
            cliente = cliente or comanda["cliente_nome"].split()[0]
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

        # Sem nada para preparar (só bebidas, chips...), o pedido já nasce
        # "pronto": não passa pela cozinha nem pela impressora dela.
        precisa_cozinha = any(p["vai_cozinha"] for p, _, _ in linhas_itens)
        with self._transacao():
            agora = self.agora()
            dia = self._dia()
            linha = self.conn.execute("SELECT MAX(numero) AS n FROM pedidos WHERE dia = ? AND tipo = 'pedido'", (dia,)).fetchone()
            numero = (linha["n"] or 0) + 1
            cur = self.conn.execute(
                "INSERT INTO pedidos (tipo, dia, numero, codigo, origem, mesa, cliente, observacao, status, "
                "total_centavos, criado_em, atualizado_em, pronto_em, usuario_id, usuario_nome, comanda_id) "
                "VALUES ('pedido', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (dia, numero, str(numero), origem, _texto(mesa, 40), _texto(cliente, 60), _texto(observacao, 300),
                 "novo" if precisa_cozinha else "pronto", total, agora, agora, None if precisa_cozinha else agora,
                 (por or {}).get("id"), (por or {}).get("nome") or "", comanda["id"] if comanda else None),
            )
            pedido_id = cur.lastrowid
            for produto, quantidade, obs in linhas_itens:
                self.conn.execute(
                    "INSERT INTO pedido_itens (pedido_id, produto_id, nome, preco_centavos, quantidade, observacao, "
                    "vai_cozinha, setor) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (pedido_id, produto["id"], produto["nome"], produto["preco_centavos"], quantidade, obs,
                     1 if produto["vai_cozinha"] else 0, produto["destino"]),
                )
            resumo = ", ".join(f"{q}x {p['nome']}" for p, q, _ in linhas_itens)
            onde = (f" — comanda {comanda['numero']}" if comanda else "") + (f" — mesa {mesa}" if mesa else "")
            sem_cozinha = "" if precisa_cozinha else " — sem preparo, já pronto"
            self._registrar(por, "Lançou pedido", f"Nº {numero}{onde}: {resumo} ({moeda(total)}){sem_cozinha}", pedido_id)
        return self.obter_pedido(pedido_id)

    def obter_pedido(self, pedido_id: int) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,)).fetchone()
            if not linha:
                return None
            pedido = dict(linha)
            pedido["pago"] = pedido["recebimento_id"] is not None
            pedido["comanda_numero"] = None
            if pedido["comanda_id"]:
                k = self.conn.execute("SELECT numero FROM comandas WHERE id = ?", (pedido["comanda_id"],)).fetchone()
                pedido["comanda_numero"] = k["numero"] if k else None
            pedido["itens"] = []
            for i in self.conn.execute(
                    "SELECT produto_id, nome, preco_centavos, quantidade, observacao, vai_cozinha, setor "
                    "FROM pedido_itens WHERE pedido_id = ? ORDER BY id", (pedido_id,)):
                item = {**dict(i), "vai_cozinha": bool(i["vai_cozinha"])}
                item["setor"] = setor_do_item(item)
                pedido["itens"].append(item)
            pedido["vai_cozinha"] = any(i["vai_cozinha"] for i in pedido["itens"])
            # Ambientes que recebem este pedido (cada um na sua impressora).
            pedido["setores"] = [s for s in ("cozinha", "bar") if any(i["setor"] == s for i in pedido["itens"])]
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
        nomes_comanda = {}
        for pedido in (self.obter_pedido(i) for i in ids):
            if pedido["comanda_id"]:
                if pedido["comanda_id"] not in nomes_comanda:
                    with self.lock:
                        nomes_comanda[pedido["comanda_id"]] = self.conn.execute(
                            "SELECT cliente_nome FROM comandas WHERE id = ?", (pedido["comanda_id"],)).fetchone()["cliente_nome"]
                chave = f"comanda:{pedido['comanda_id']}"
                titulo = f"Comanda {pedido['comanda_numero']} · {nomes_comanda[pedido['comanda_id']]}"
            elif pedido["mesa"]:
                chave, titulo = "mesa:" + pedido["mesa"], "Mesa " + pedido["mesa"]
            else:
                chave = f"pedido:{pedido['id']}"
                titulo = f"Pedido nº {pedido['codigo']}" + (f" · {pedido['cliente']}" if pedido["cliente"] else "")
            grupo = grupos.setdefault(chave, {"chave": chave, "titulo": titulo, "pedidos": [], "total": 0})
            grupo["pedidos"].append(pedido)
            grupo["total"] += pedido["total_centavos"]
        return list(grupos.values())

    # --- Clientes ---------------------------------------------------------

    def _hoje(self) -> datetime:
        return datetime.fromtimestamp(self.agora())

    def _cliente_dict(self, linha, com_cpf: bool = True) -> dict:
        c = dict(linha)
        c["aceita_mensagens"] = bool(c["aceita_mensagens"])
        c["telefone_formatado"] = formatar_telefone(c["telefone"]) if not c["removido_em"] else ""
        c["cpf_formatado"] = formatar_cpf(c["cpf"]) if com_cpf else ""
        if not com_cpf:
            c["cpf"] = None
        c["aniversario_hoje"] = False
        if c["nascimento"]:
            data, _ = proximo_aniversario(c["nascimento"], self._hoje())
            c["aniversario_hoje"] = data.date() == self._hoje().date()
        return c

    def _validar_cliente(self, dados: dict, atual: Optional[dict] = None) -> dict:
        nome = _texto(dados.get("nome", (atual or {}).get("nome")), 80)
        if not nome:
            raise ErroNegocio("Informe o nome do cliente.")
        telefone = normalizar_telefone(dados.get("telefone", (atual or {}).get("telefone")), self.config()["ddd_padrao"])
        return {
            "nome": nome,
            "telefone": telefone,
            "cpf": validar_cpf(dados.get("cpf", (atual or {}).get("cpf"))),
            "nascimento": validar_nascimento(dados.get("nascimento", (atual or {}).get("nascimento")), self._hoje()),
            "aceita_mensagens": 1 if dados.get("aceita_mensagens", (atual or {}).get("aceita_mensagens")) else 0,
            "observacao": _texto(dados.get("observacao", (atual or {}).get("observacao")), 300),
        }

    def _conferir_duplicado(self, valores: dict, ignorar_id: Optional[int] = None) -> None:
        for campo, rotulo in (("telefone", "esse telefone"), ("cpf", "esse CPF")):
            if not valores[campo]:
                continue
            linha = self.conn.execute(
                f"SELECT id, nome FROM clientes WHERE {campo} = ? AND removido_em IS NULL AND id != ?",
                (valores[campo], ignorar_id or 0)).fetchone()
            if linha:
                raise ErroNegocio(f"Já existe cliente cadastrado com {rotulo}: {linha['nome']}.")

    def criar_cliente(self, dados: dict, por: Optional[dict] = None) -> dict:
        valores = self._validar_cliente(dados)
        agora = self.agora()
        with self._transacao():
            self._conferir_duplicado(valores)
            cur = self.conn.execute(
                "INSERT INTO clientes (nome, telefone, cpf, nascimento, aceita_mensagens, consentimento_em, observacao, "
                "criado_em, atualizado_em) VALUES (:nome, :telefone, :cpf, :nascimento, :aceita_mensagens, :consentimento, "
                ":observacao, :agora, :agora)",
                {**valores, "consentimento": agora if valores["aceita_mensagens"] else None, "agora": agora},
            )
            self._registrar(por, "Cadastrou cliente", f"{valores['nome']} — {formatar_telefone(valores['telefone'])}"
                            + ("; aceita receber mensagens" if valores["aceita_mensagens"] else "; não aceita mensagens"))
        return self.obter_cliente(cur.lastrowid)

    def obter_cliente(self, cliente_id, com_cpf: bool = True) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
            return self._cliente_dict(linha, com_cpf) if linha else None

    def atualizar_cliente(self, cliente_id: int, dados: dict, por: Optional[dict] = None) -> dict:
        atual = self.obter_cliente(cliente_id)
        if not atual or atual["removido_em"]:
            raise ErroNegocio("Cliente não encontrado.")
        valores = self._validar_cliente(dados, atual)
        mudancas = [campo for campo in ("nome", "telefone", "cpf", "nascimento", "observacao") if valores[campo] != atual[campo]]
        consentimento = atual["consentimento_em"]
        if bool(valores["aceita_mensagens"]) != atual["aceita_mensagens"]:
            mudancas.append("passou a aceitar mensagens" if valores["aceita_mensagens"] else "deixou de aceitar mensagens")
            consentimento = self.agora() if valores["aceita_mensagens"] else None
        with self._transacao():
            self._conferir_duplicado(valores, ignorar_id=cliente_id)
            self.conn.execute(
                "UPDATE clientes SET nome = :nome, telefone = :telefone, cpf = :cpf, nascimento = :nascimento, "
                "aceita_mensagens = :aceita_mensagens, consentimento_em = :consentimento, observacao = :observacao, "
                "atualizado_em = :agora WHERE id = :id",
                {**valores, "consentimento": consentimento, "agora": self.agora(), "id": cliente_id},
            )
            if mudancas:
                self._registrar(por, "Alterou cliente", f"{atual['nome']}: " + ", ".join(mudancas))
        return self.obter_cliente(cliente_id)

    def remover_dados_cliente(self, cliente_id: int, por: Optional[dict] = None) -> None:
        """Apaga os dados pessoais a pedido do cliente (LGPD). As comandas e
        vendas continuam nos relatórios, mas sem nome, telefone, CPF ou
        data de nascimento."""
        atual = self.obter_cliente(cliente_id)
        if not atual or atual["removido_em"]:
            raise ErroNegocio("Cliente não encontrado.")
        with self.lock:
            aberta = self.conn.execute("SELECT 1 FROM comandas WHERE cliente_id = ? AND fechada_em IS NULL", (cliente_id,)).fetchone()
        if aberta:
            raise ErroNegocio("Esse cliente está com uma comanda aberta. Feche a comanda antes.")
        with self._transacao():
            self.conn.execute(
                "UPDATE clientes SET nome = 'Cliente removido', telefone = ?, cpf = NULL, nascimento = NULL, "
                "aceita_mensagens = 0, consentimento_em = NULL, observacao = '', removido_em = ?, atualizado_em = ? "
                "WHERE id = ?", (f"removido-{cliente_id}", self.agora(), self.agora(), cliente_id))
            self.conn.execute("UPDATE comandas SET cliente_nome = 'Cliente removido' WHERE cliente_id = ?", (cliente_id,))
            self._registrar(por, "Apagou dados do cliente (LGPD)", f"cadastro nº {cliente_id}")

    def buscar_clientes(self, texto: str, com_cpf: bool = False, limite: int = 15) -> list:
        texto = _texto(texto, 80)
        if not texto:
            return []
        digitos = _digitos(texto)
        sql = "SELECT * FROM clientes WHERE removido_em IS NULL AND (nome LIKE ?"
        params = [f"%{texto}%"]
        if len(digitos) >= 3:
            sql += " OR telefone LIKE ? OR cpf LIKE ?"
            params += [f"%{digitos}%", f"%{digitos}%"]
        sql += ") ORDER BY nome COLLATE NOCASE LIMIT ?"
        params.append(limite)
        with self.lock:
            return [self._cliente_dict(l, com_cpf) for l in self.conn.execute(sql, params)]

    def listar_clientes(self, busca: str = "") -> list:
        """Lista completa com visitas, última visita e total gasto."""
        sql = ("SELECT c.*, "
               "(SELECT COUNT(*) FROM comandas k WHERE k.cliente_id = c.id) AS visitas, "
               "(SELECT MAX(aberta_em) FROM comandas k WHERE k.cliente_id = c.id) AS ultima_visita, "
               "(SELECT COALESCE(SUM(p.total_centavos), 0) FROM pedidos p JOIN comandas k ON k.id = p.comanda_id "
               " WHERE k.cliente_id = c.id AND p.recebimento_id IS NOT NULL) AS total_gasto "
               "FROM clientes c WHERE c.removido_em IS NULL")
        params = []
        if busca:
            sql += " AND (c.nome LIKE ? OR c.telefone LIKE ? OR c.cpf LIKE ?)"
            params = [f"%{busca}%", f"%{_digitos(busca) or busca}%", f"%{_digitos(busca) or busca}%"]
        with self.lock:
            return [self._cliente_dict(l) for l in self.conn.execute(sql + " ORDER BY c.nome COLLATE NOCASE", params)]

    def aniversariantes(self, dias: int = 7) -> list:
        """Clientes que fazem aniversário de hoje até `dias` dias à frente."""
        hoje = self._hoje()
        campanha = f"aniversario-{hoje.year}"
        resultado = []
        with self.lock:
            enviados = {l["cliente_id"] for l in self.conn.execute(
                "SELECT cliente_id FROM mensagens_enviadas WHERE campanha = ?", (campanha,))}
            linhas = self.conn.execute(
                "SELECT * FROM clientes WHERE removido_em IS NULL AND nascimento IS NOT NULL").fetchall()
        for linha in linhas:
            data, idade = proximo_aniversario(linha["nascimento"], hoje)
            faltam = (data.date() - hoje.date()).days
            if faltam <= dias:
                c = self._cliente_dict(linha, com_cpf=False)
                c.update({"faltam_dias": faltam, "data_aniversario": data.strftime("%Y-%m-%d"), "idade": idade,
                          "parabens_enviado": linha["id"] in enviados})
                resultado.append(c)
        resultado.sort(key=lambda c: (c["faltam_dias"], c["nome"].lower()))
        return resultado

    PUBLICOS = {
        "todos": "Todos que aceitam mensagens",
        "aniversario_mes": "Aniversariantes do mês",
        "aniversario_semana": "Aniversariantes dos próximos 7 dias",
        "sumidos": "Clientes que não vêm há mais de 30 dias",
        "novos": "Clientes cadastrados nos últimos 30 dias",
    }

    def publico_campanha(self, publico: str, campanha: str) -> list:
        """Quem vai receber a mensagem: SÓ clientes que aceitaram receber."""
        if publico not in self.PUBLICOS:
            raise ErroNegocio("Público inválido.")
        campanha = _texto(campanha, 60)
        if not campanha:
            raise ErroNegocio("Dê um nome para a campanha (ex.: Promoção de sexta).")
        hoje = self._hoje()
        limite_30 = self.agora() - 30 * 86400
        with self.lock:
            linhas = self.conn.execute(
                "SELECT c.*, (SELECT MAX(aberta_em) FROM comandas k WHERE k.cliente_id = c.id) AS ultima_visita "
                "FROM clientes c WHERE c.removido_em IS NULL AND c.aceita_mensagens = 1 ORDER BY c.nome COLLATE NOCASE"
            ).fetchall()
            enviados = {l["cliente_id"]: l["enviado_em"] for l in self.conn.execute(
                "SELECT cliente_id, MAX(enviado_em) AS enviado_em FROM mensagens_enviadas WHERE campanha = ? "
                "GROUP BY cliente_id", (campanha,))}
        resultado = []
        for linha in linhas:
            if publico.startswith("aniversario"):
                if not linha["nascimento"]:
                    continue
                data, _ = proximo_aniversario(linha["nascimento"], hoje)
                if publico == "aniversario_mes" and datetime.strptime(linha["nascimento"], "%Y-%m-%d").month != hoje.month:
                    continue
                if publico == "aniversario_semana" and (data.date() - hoje.date()).days > 7:
                    continue
            elif publico == "sumidos" and not (linha["ultima_visita"] and linha["ultima_visita"] < limite_30):
                continue
            elif publico == "novos" and linha["criado_em"] < limite_30:
                continue
            c = self._cliente_dict(linha, com_cpf=False)
            c["enviado_em"] = enviados.get(linha["id"])
            resultado.append(c)
        return resultado

    def registrar_mensagem(self, cliente_id: int, campanha: str, texto: str, por: Optional[dict] = None) -> None:
        cliente = self.obter_cliente(cliente_id, com_cpf=False)
        if not cliente or cliente["removido_em"]:
            raise ErroNegocio("Cliente não encontrado.")
        if not cliente["aceita_mensagens"]:
            raise ErroNegocio(f"{cliente['nome']} não autorizou receber mensagens.")
        campanha = _texto(campanha, 60) or "avulsa"
        with self._transacao():
            self.conn.execute(
                "INSERT INTO mensagens_enviadas (cliente_id, campanha, texto, usuario_nome, enviado_em) VALUES (?, ?, ?, ?, ?)",
                (cliente_id, campanha, _texto(texto, 2000), (por or {}).get("nome") or "Sistema", self.agora()))
            self._registrar(por, "Enviou WhatsApp", f"{campanha} — para {cliente['nome']} ({cliente['telefone_formatado']})")

    def registrar_mensagens(self, cliente_ids: list, campanha: str, texto: str, por: Optional[dict] = None) -> int:
        """Marca vários clientes como "já recebeu" de uma vez (ex.: depois de
        mandar pela lista de transmissão do WhatsApp). Quem não autorizou
        mensagens é ignorado. Devolve quantos foram marcados."""
        campanha = _texto(campanha, 60) or "avulsa"
        ids = sorted({int(i) for i in cliente_ids or [] if str(i).isdigit()})
        if not ids:
            raise ErroNegocio("Nenhum cliente na lista.")
        agora = self.agora()
        with self._transacao():
            marcas = ",".join("?" * len(ids))
            validos = [l["id"] for l in self.conn.execute(
                f"SELECT id FROM clientes WHERE id IN ({marcas}) AND removido_em IS NULL AND aceita_mensagens = 1", ids)]
            self.conn.executemany(
                "INSERT INTO mensagens_enviadas (cliente_id, campanha, texto, usuario_nome, enviado_em) VALUES (?, ?, ?, ?, ?)",
                [(i, campanha, _texto(texto, 2000), (por or {}).get("nome") or "Sistema", agora) for i in validos])
            if validos:
                self._registrar(por, "Enviou WhatsApp", f"{campanha} — para {len(validos)} clientes (lista de transmissão)")
        return len(validos)

    @staticmethod
    def contatos_vcard(clientes: list) -> str:
        """Arquivo .vcf para importar os clientes nos contatos do celular —
        a lista de transmissão do WhatsApp só entrega para quem está salvo."""
        def esc(v):
            return str(v).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", " ")
        cartoes = []
        for c in clientes:
            cartoes.append("\r\n".join([
                "BEGIN:VCARD", "VERSION:3.0", f"FN:{esc(c['nome'])}", f"N:;{esc(c['nome'])};;;",
                f"TEL;TYPE=CELL:+55{c['telefone']}", "END:VCARD"]))
        return "\r\n".join(cartoes) + ("\r\n" if cartoes else "")

    def clientes_csv(self) -> str:
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";")
        w.writerow(["Nome", "Telefone", "CPF", "Nascimento", "Aceita mensagens", "Visitas", "Última visita",
                    "Total gasto", "Cadastrado em", "Observação"])
        for c in self.listar_clientes():
            data = lambda ts: datetime.fromtimestamp(ts).strftime("%d/%m/%Y") if ts else ""
            nasc = datetime.strptime(c["nascimento"], "%Y-%m-%d").strftime("%d/%m/%Y") if c["nascimento"] else ""
            w.writerow([c["nome"], c["telefone_formatado"], c["cpf_formatado"], nasc,
                        "Sim" if c["aceita_mensagens"] else "Não", c["visitas"], data(c["ultima_visita"]),
                        f"{c['total_gasto'] / 100:.2f}".replace(".", ","), data(c["criado_em"]), c["observacao"]])
        return "\ufeff" + saida.getvalue()

    # --- Comandas ------------------------------------------------------------

    def _comanda_dict(self, linha) -> dict:
        k = dict(linha)
        with self.lock:
            soma = self.conn.execute(
                "SELECT COALESCE(SUM(total_centavos), 0) AS total, "
                "COALESCE(SUM(CASE WHEN recebimento_id IS NULL THEN total_centavos ELSE 0 END), 0) AS a_receber, "
                "COUNT(*) AS pedidos FROM pedidos WHERE comanda_id = ? AND status != 'cancelado'", (k["id"],)).fetchone()
        cliente = self.obter_cliente(k["cliente_id"], com_cpf=False)
        k.update({"total": soma["total"], "a_receber": soma["a_receber"], "qtd_pedidos": soma["pedidos"],
                  "aberta": k["fechada_em"] is None,
                  "telefone_formatado": cliente["telefone_formatado"] if cliente else "",
                  "aniversario_hoje": bool(cliente and cliente["aniversario_hoje"])})
        return k

    def obter_comanda(self, comanda_id) -> Optional[dict]:
        with self.lock:
            linha = self.conn.execute("SELECT * FROM comandas WHERE id = ?", (comanda_id,)).fetchone()
        return self._comanda_dict(linha) if linha else None

    def listar_comandas(self, abertas: bool = True) -> list:
        with self.lock:
            sql = "SELECT * FROM comandas WHERE fechada_em IS " + ("NULL" if abertas else "NOT NULL")
            linhas = self.conn.execute(sql + " ORDER BY aberta_em").fetchall()
        comandas = [self._comanda_dict(l) for l in linhas]
        comandas.sort(key=lambda k: (not k["numero"].isdigit(), int(k["numero"]) if k["numero"].isdigit() else 0, k["numero"]))
        return comandas

    def abrir_comanda(self, cliente_id, numero: str = "", por: Optional[dict] = None) -> dict:
        cliente = self.obter_cliente(cliente_id, com_cpf=False)
        if not cliente or cliente["removido_em"]:
            raise ErroNegocio("Cliente não encontrado.")
        numero = _texto(numero, 20)
        with self._transacao():
            abertas = {l["numero"]: l for l in self.conn.execute(
                "SELECT numero, cliente_id, cliente_nome FROM comandas WHERE fechada_em IS NULL")}
            ja_aberta = [l for l in abertas.values() if l["cliente_id"] == cliente["id"]]
            if ja_aberta:
                raise ErroNegocio(f"{cliente['nome']} já está com a comanda {ja_aberta[0]['numero']} aberta.")
            if numero:
                if numero in abertas:
                    raise ErroNegocio(f"A comanda {numero} já está em uso por {abertas[numero]['cliente_nome']}.")
            else:
                # Próximo número livre (os cartões físicos voltam a ser usados).
                n = 1
                while str(n) in abertas:
                    n += 1
                numero = str(n)
            cur = self.conn.execute(
                "INSERT INTO comandas (numero, cliente_id, cliente_nome, aberta_em, aberta_por_nome) VALUES (?, ?, ?, ?, ?)",
                (numero, cliente["id"], cliente["nome"], self.agora(), (por or {}).get("nome") or "Sistema"))
            self._registrar(por, "Abriu comanda", f"Comanda {numero} — {cliente['nome']}"
                            + (" (aniversariante do dia)" if cliente["aniversario_hoje"] else ""))
        return self.obter_comanda(cur.lastrowid)

    def _exigir_comanda_aberta(self, comanda_id) -> dict:
        comanda = self.obter_comanda(comanda_id)
        if not comanda:
            raise ErroNegocio("Comanda não encontrada.")
        if not comanda["aberta"]:
            raise ErroNegocio(f"A comanda {comanda['numero']} já foi fechada.")
        return comanda

    def fechar_comanda(self, comanda_id, por: Optional[dict] = None, motivo: str = "sem consumo") -> dict:
        """Fecha a comanda de quem saiu sem nada a pagar (a comanda paga
        fecha sozinha ao receber)."""
        comanda = self._exigir_comanda_aberta(comanda_id)
        if comanda["a_receber"]:
            raise ErroNegocio(f"A comanda {comanda['numero']} ainda tem {moeda(comanda['a_receber'])} a receber.")
        with self._transacao():
            self._fechar_comanda_sem_commit(comanda, por, motivo)
        return self.obter_comanda(comanda_id)

    def _fechar_comanda_sem_commit(self, comanda: dict, por: Optional[dict], motivo: str) -> None:
        self.conn.execute(
            "UPDATE comandas SET fechada_em = ?, fechada_por_nome = ?, motivo_fechamento = ? WHERE id = ? AND fechada_em IS NULL",
            (self.agora(), (por or {}).get("nome") or "Sistema", motivo, comanda["id"]))
        self._registrar(por, "Fechou comanda", f"Comanda {comanda['numero']} — {comanda['cliente_nome']} ({motivo})")

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
        comandas = sorted({p["comanda_numero"] for p in pedidos if p["comanda_numero"]})
        codigos = ", ".join(p["codigo"] for p in pedidos)
        descricao = ((f"Comanda {', '.join(comandas)} — " if comandas else "")
                     + (f"Mesa {', '.join(mesas)} — " if mesas else "") + f"pedido(s) {codigos}")
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
            # Comanda totalmente paga: o cliente pode sair, a comanda fecha.
            for comanda_id in {p["comanda_id"] for p in pedidos if p["comanda_id"]}:
                pendente = self.conn.execute(
                    "SELECT 1 FROM pedidos WHERE comanda_id = ? AND status != 'cancelado' AND recebimento_id IS NULL",
                    (comanda_id,)).fetchone()
                linha = self.conn.execute("SELECT * FROM comandas WHERE id = ? AND fechada_em IS NULL", (comanda_id,)).fetchone()
                if linha and not pendente:
                    self._fechar_comanda_sem_commit(dict(linha), por, "paga")
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
            # Os pedidos voltam a ficar "a receber" — e a comanda que tinha
            # fechado por causa desse pagamento volta a ficar aberta.
            for l in self.conn.execute(
                "SELECT DISTINCT comanda_id FROM pedidos WHERE recebimento_id = ? AND comanda_id IS NOT NULL", (rid,)).fetchall():
                self.conn.execute("UPDATE comandas SET fechada_em = NULL, fechada_por_nome = '', motivo_fechamento = '' "
                                  "WHERE id = ? AND motivo_fechamento = 'paga'", (l["comanda_id"],))
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

    def recebimentos_periodo(self, de: str, ate: str) -> list:
        ini, fim = self._periodo(de, ate)
        with self.lock:
            ids = [l["id"] for l in self.conn.execute(
                "SELECT id FROM recebimentos WHERE criado_em >= ? AND criado_em < ? ORDER BY criado_em", (ini, fim))]
        return [self.obter_recebimento(i) for i in ids]

    def comandas_periodo(self, de: str, ate: str) -> list:
        ini, fim = self._periodo(de, ate)
        with self.lock:
            linhas = self.conn.execute(
                "SELECT * FROM comandas WHERE aberta_em >= ? AND aberta_em < ? ORDER BY aberta_em", (ini, fim)).fetchall()
        return [self._comanda_dict(l) for l in linhas]

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
