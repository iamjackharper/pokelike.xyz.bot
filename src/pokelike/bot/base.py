"""The interface every bot implements.

A bot is one thing only: something that, given the state, says **which action to
take**. Everything else — starting the browser, applying the move, computing the
score — is none of its business.

    class MyBot(Bot):
        def choose(self, state):
            return 0          # index into state["actions"]

The index is the position in `state["actions"]`, the same numbered list you see
when playing from the CLI. Returning an index out of range makes the move fail,
so a bot must always stay within `len(state["actions"])`.

The two hooks `on_start` and `on_end` are for bots that need memory across
turns:

- an **LLM** resets its conversation in `on_start` and closes it in `on_end`;
- an **RL** algorithm accumulates the trajectory and receives the final score in
  `on_end`, which is its reward signal;
- a **scripted** bot resets its move counter in `on_start`.

Bots that need neither can ignore them: both already have empty bodies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Bot(ABC):
    """Base for every bot. `choose` is the only required method."""

    name = "bot"

    @abstractmethod
    def choose(self, state: dict[str, Any]) -> int:
        """Index of the chosen action within `state["actions"]`.

        `state` is the full dict: `team`, `bag`, `map`, `run`, `actions`,
        `steps`, `screen`. See `core/render.py` for how to read it.
        """

    def on_start(self, seed: int) -> None:
        """Called before the first turn of each run."""

    def on_end(self, state: dict[str, Any], score: dict[str, Any] | None) -> None:
        """Called once the run is over, with the final state and the score."""

    def artifacts(self) -> list:
        """What to archive alongside a leaderboard result.

        Return a list of `pokelike.leaderboard.Artifact`: weights, prompts, the
        model you called, the hyperparameters you trained with. A bot made of
        plain rules has nothing to declare and can ignore this.

        Whatever is returned here is copied into the submission folder and
        hashed, so the result can never be separated from what produced it.
        """
        return []
