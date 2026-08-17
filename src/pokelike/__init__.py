"""pokelike — gioca headless a pokelike.xyz da Python, CLI o API HTTP."""

from .core.game import ErroreAzione, Partita

__all__ = ["Partita", "ErroreAzione"]
__version__ = "0.1.0"
