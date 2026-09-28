"""Gera icon/icon.ico (executável e instalador) com o mesmo desenho do ícone
da bandeja. Rodado automaticamente pelo build_tools/build_windows.ps1."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from comandas.bandeja import imagem_icone  # noqa: E402


def main() -> None:
    destino = Path(__file__).parent / "icon.ico"
    tamanhos = [16, 24, 32, 48, 64, 128, 256]
    imagem_icone(256).save(destino, sizes=[(t, t) for t in tamanhos])
    print(f"Ícone gerado em {destino}")


if __name__ == "__main__":
    main()
