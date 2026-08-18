"""pokelike — play pokelike.xyz headless from Python, a CLI or an HTTP API.

    from pokelike import session, open_game, play, compare

    with session() as game:                       # a script
        obs = game.reset(seed=42)
        obs = game.step(0)

    game = open_game()                            # a notebook: survives the cell
    obs = game.reset(seed=42)

    play(MyBot(), seed=42)                        # one run, with its trace
    compare({"mine": MyBot()}, seeds=range(20))   # against random, paired

See `interfaces/python/example.ipynb` for the cell-by-cell walkthrough.
"""

from .core.game import Game, IllegalAction
from .interfaces.python import compare, evaluate, open_game, play, session

__all__ = [
    "Game", "IllegalAction",
    "session", "open_game", "play", "evaluate", "compare",
]
__version__ = "0.1.0"
