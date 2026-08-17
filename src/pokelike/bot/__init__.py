"""The bots: whoever decides the moves.

To add one: create a file here with a class inheriting from `Bot`, then register
it in `AVAILABLE` so it can be used from the command line with
`pokelike bot --bot <name>`.

    # src/pokelike/bot/mine.py
    from .base import Bot

    class MyBot(Bot):
        name = "mine"
        def choose(self, state):
            return 0

    # then, in AVAILABLE below:
    "mine": ("mine", "MyBot"),
"""

from __future__ import annotations

from importlib import import_module

from .base import Bot
from .random_bot import RandomBot

# command-line name -> (module inside this package, class)
# The module is imported only when needed, so a bot with heavy dependencies
# (an LLM client, torch) does not slow down anyone using the simple ones.
AVAILABLE: dict[str, tuple[str, str]] = {
    "random": ("random_bot", "RandomBot"),
    "llm": ("llm", "LLMBot"),
    "dyna_q": ("dyna_q", "DynaQBot"),
}


def create(name: str, seed: int = 0) -> Bot:
    """Builds a bot from a name registered in `AVAILABLE`."""
    if name not in AVAILABLE:
        available = ", ".join(sorted(AVAILABLE))
        raise KeyError(f"unknown bot '{name}' — available: {available}")
    module, cls = AVAILABLE[name]
    return getattr(import_module(f".{module}", __package__), cls)(seed=seed)


__all__ = ["Bot", "RandomBot", "AVAILABLE", "create"]
