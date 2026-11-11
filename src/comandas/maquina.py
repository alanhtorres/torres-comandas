"""O papel deste computador na loja, guardado em maquina.json na pasta de dados.

- "principal": guarda os dados (banco) e serve as outras máquinas. Precisa
  ficar ligado enquanto a loja funciona.
- "terminal": não guarda dados; mostra as telas do computador principal.

Também guarda a tela que esta máquina abre ao ligar (ex.: a TV abre o painel,
o PC da cozinha abre a cozinha) e se abre em tela cheia.
"""
import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

MODOS = ("principal", "terminal")
TELAS = ("", "caixa", "comandas", "garcom", "cozinha", "bar", "painel", "admin")
# Ambientes criados pelo administrador (pizzaria, confeitaria...) também são telas.
CHAVE_TELA = re.compile(r"^[a-z0-9]{1,20}$")


@dataclass
class Maquina:
    modo: Optional[str] = None  # None = ainda não escolheu (primeira vez)
    servidor: str = ""          # terminal: endereço do principal (achado sozinho na rede)
    id: str = ""                # terminal: id do sistema, para reencontrá-lo se o IP mudar
    loja: str = ""
    tela: str = ""              # "" = a última aba usada
    tela_cheia: bool = False

    @classmethod
    def carregar(cls, pasta: Path) -> "Maquina":
        arquivo = pasta / "maquina.json"
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        conhecidos = {f.name for f in fields(cls)}
        m = cls(**{k: v for k, v in dados.items() if k in conhecidos})
        if m.modo not in MODOS:
            m.modo = None
        if m.tela not in TELAS and not CHAVE_TELA.match(str(m.tela)):
            m.tela = ""
        # Instalação de antes desta versão: já tem os dados aqui, então é o principal.
        if m.modo is None and (pasta / "comandas.db").exists():
            m.modo = "principal"
        return m

    def salvar(self, pasta: Path) -> None:
        (pasta / "maquina.json").write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    def caminho_inicial(self) -> str:
        """O painel abre sozinho (TV, sem login); as outras telas abrem nas abas."""
        if self.tela == "painel":
            return "/painel"
        return "/area" + (f"?tela={self.tela}" if self.tela else "")
