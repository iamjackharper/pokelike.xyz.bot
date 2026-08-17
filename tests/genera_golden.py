"""Records the golden fingerprints.

    uv run python tests/genera_golden.py

Run this ONLY when the game itself has changed (a new release upstream) and you
have checked by hand that the new behaviour is correct. Regenerating it to make
a failing test go green defeats the whole point.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from impronta import CASI, impronta, salva_golden  # noqa: E402

from pokelike.assets import ServerAsset  # noqa: E402
from pokelike.core.game import Partita  # noqa: E402

RADICE = Path(__file__).resolve().parents[1]


def main() -> int:
    if not (RADICE / "site" / "index.html").is_file():
        print("copia offline assente: esegui prima `pokelike setup`", file=sys.stderr)
        return 2

    dati = {}
    with ServerAsset(RADICE / "site", porta=8552) as s, Partita(url=s.url) as g:
        for seed, politica in CASI:
            chiave = f"{seed}-{politica}"
            print(f"  {chiave} ...", flush=True)
            dati[chiave] = impronta(g, seed, politica)
            print(f"    {dati[chiave]['passi']} passi, {dati[chiave]['punti']} punti")

    salva_golden(dati)
    print(f"\nsalvate {len(dati)} impronte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
