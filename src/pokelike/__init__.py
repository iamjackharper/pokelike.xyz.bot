"""pokelike — play pokelike.xyz headless from Python, a CLI or an HTTP API."""

from .core.game import Game, IllegalAction

__all__ = ["Game", "IllegalAction"]
__version__ = "0.1.0"
