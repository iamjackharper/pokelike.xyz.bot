"""I bot: chi decide le mosse.

Per aggiungerne uno: crea un file qui dentro con una classe che eredita da `Bot`,
poi registrala in `DISPONIBILI` per poterla usare da riga di comando con
`pokelike bot --bot <nome>`.

    # src/pokelike/bot/mio.py
    from .base import Bot

    class MioBot(Bot):
        nome = "mio"
        def scegli(self, stato):
            return 0

    # qui sotto, in DISPONIBILI:
    "mio": ("mio", "MioBot"),
"""

from __future__ import annotations

from importlib import import_module

from .base import Bot
from .casuale import BotCasuale

# nome da riga di comando -> (modulo dentro questo pacchetto, classe)
# Il modulo si importa solo quando serve: così un bot con dipendenze pesanti
# (un LLM, torch) non rallenta chi usa solo quello casuale.
DISPONIBILI: dict[str, tuple[str, str]] = {
    "casuale": ("casuale", "BotCasuale"),
    "llm": ("llm", "BotLLM"),
}


def crea(nome: str, seed: int = 0) -> Bot:
    """Costruisce un bot dal nome registrato in `DISPONIBILI`."""
    if nome not in DISPONIBILI:
        disponibili = ", ".join(sorted(DISPONIBILI))
        raise KeyError(f"bot '{nome}' sconosciuto — disponibili: {disponibili}")
    modulo, classe = DISPONIBILI[nome]
    return getattr(import_module(f".{modulo}", __package__), classe)(seed=seed)


__all__ = ["Bot", "BotCasuale", "DISPONIBILI", "crea"]
