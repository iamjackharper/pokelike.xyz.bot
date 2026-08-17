"""A bot that picks uniformly at random among the legal actions.

It looks at nothing: not HP, not types, not what lies ahead on the map. It is
the baseline — it dies within a couple of dozen moves without ever clearing the
first map, so any real player has to beat it.

It is reproducible: the same seed replays the same run.
"""

from __future__ import annotations

import random
from typing import Any

from .base import Bot


class RandomBot(Bot):
    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed
        self._rng = random.Random(seed)

    def on_start(self, seed: int) -> None:
        # Reseed from the run's seed so the sequence of choices belongs to the
        # run, not to how many runs came before it.
        self._rng = random.Random(seed)

    def choose(self, state: dict[str, Any]) -> int:
        return self._rng.randrange(len(state["actions"]))
