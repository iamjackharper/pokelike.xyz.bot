"""The shared game logic. CLI, API and bots are all thin faces over this class.

The model is a turn-based environment:

    g = Game()
    g.reset(seed=42)
    g.state()      -> dict with team, map and legal actions
    g.step(1)      -> apply action 1, return the new state
    g.score()      -> score computed with the game's own formula

Between one decision and the next the engine does plenty on its own (plays out
the battle, shows level-ups, banners). Those are not player choices, so
`_settle()` runs them through and only hands control back when there really is
more than one option, or the run is over.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .browser import Session, normalise_seed


class IllegalAction(RuntimeError):
    """The action is not valid in the current state."""


@dataclass
class Game:
    url: str = "http://127.0.0.1:8422/"
    watch: bool = False
    max_delay: int = 1
    scoring: bool = True
    load_images: bool = True

    session: Session | None = field(default=None, repr=False)
    seed: int | None = None
    steps: int = 0
    score_hook: dict[str, Any] | None = field(default=None, repr=False)
    last_alive: dict[str, Any] | None = field(default=None, repr=False)
    _last: dict[str, Any] | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ setup

    def open(self) -> None:
        self.session = Session(url=self.url, watch=self.watch, max_delay=self.max_delay,
                               load_images=self.load_images)
        self.session.start()

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None

    def __enter__(self) -> "Game":
        self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -------------------------------------------------------------------- run

    def reset(self, seed: int = 0) -> dict[str, Any]:
        """Starts a run in Story mode, Kanto, classic rules.

        Picking the trainer and the starter is NOT done here: those stay player
        decisions and show up as the first two turns.

        The seed is checked BEFORE anything is played: an unusable one used to
        surface only at the end, when the finished run was handed to the
        registry, so the whole run was lost to a mistake known at step zero.
        """
        seed = normalise_seed(seed)
        if self.session is None:
            self.open()
        assert self.session is not None

        # The normalised value, not the one passed in: what gets recorded has to
        # be the seed that will actually reproduce this run.
        self.seed = seed
        self.steps = 0
        self.last_alive = None
        page = self.session.load(seed)

        page.evaluate("() => { const b = document.getElementById('btn-history-run'); if (b) b.click(); }")
        page.wait_for_timeout(300)
        page.evaluate(
            "() => { const b = document.querySelector('.history-region-btn');"
            " if (b) b.dispatchEvent(new MouseEvent('click', {bubbles: true})); }"
        )
        page.wait_for_timeout(300)

        if self.scoring:
            # Scoring is a bonus: if the hook fails the run must still go on.
            try:
                self.score_hook = page.evaluate("() => window.__pk_attach_score()")
            except Exception as e:  # noqa: BLE001
                self.score_hook = {"ok": False, "reason": str(e)[:200]}

        return self._settle()

    # ------------------------------------------------------------ observation

    def state(self) -> dict[str, Any]:
        """The current state. Read-only: it does not advance the game."""
        if self.session is None or self.session.page is None:
            raise RuntimeError("no run open: call reset()")
        obs = self.session.page.evaluate("() => window.__pk_obs()")
        obs["steps"] = self.steps
        obs["seed"] = self.seed
        obs["done"] = self._is_terminal()
        self._last = obs
        # On the game-over screen the engine wipes `state`: empty team, no
        # badges. Keep the last snapshot taken while the run was alive, or the
        # end-of-run summary would have nothing to report.
        if obs.get("team"):
            self.last_alive = obs
        return obs

    def actions(self) -> list[dict[str, Any]]:
        return self.state().get("actions", [])

    # ----------------------------------------------------------------- action

    def step(self, index: int) -> dict[str, Any]:
        """Applies legal action `index` and returns the new state."""
        assert self.session is not None and self.session.page is not None
        actions = (self._last or self.state()).get("actions", [])
        if not 0 <= index < len(actions):
            raise IllegalAction(
                f"index {index} out of range: there are {len(actions)} legal actions"
            )
        choice = actions[index]
        ok = self.session.page.evaluate("c => window.__pk_apply(c)", choice)
        if not ok:
            raise IllegalAction(f"the engine refused the action: {choice}")
        self.steps += 1
        self.session.page.wait_for_timeout(70)
        return self._settle()

    # ------------------------------------------------------- free actions

    def reorder(self, a: int, b: int) -> dict[str, Any]:
        """Swaps two team slots and returns the new state.

        Slot 0 leads, so this is a genuine decision and not decoration. It is
        deliberately NOT one of `step`'s actions: reordering does not consume
        the turn, and a team of six would otherwise add fifteen swap pairs to
        the list at every single map node, drowning the actual moves.

        `steps` does not advance, for the same reason.
        """
        assert self.session is not None and self.session.page is not None
        team = (self._last or self.state()).get("team") or []
        for name, i in (("a", a), ("b", b)):
            if not 0 <= i < len(team):
                raise IllegalAction(
                    f"{name}={i} is not a team slot: there are {len(team)} Pokemon"
                )
        if a == b:
            raise IllegalAction(f"a and b are both {a}: that swap does nothing")
        if not self.session.page.evaluate("([x, y]) => window.__pk_reorder(x, y)", [a, b]):
            raise IllegalAction(f"the engine refused the swap {a} <-> {b}")
        return self.state()

    # ------------------------------------------------------------------ score

    def score(self) -> dict[str, Any] | None:
        """Score using the game's own formula.

            500 if completed + 5·KOs − 10·faints + 50·maps
            + 20·legendaries + 20·shinies + time bonus

        Returns None when the stats hook is not attached.
        """
        if self.session is None or self.session.page is None:
            return None
        completed = (self._last or {}).get("screen") == "win-screen"
        return self.session.page.evaluate("c => window.__pk_score(c)", completed)

    # --------------------------------------------------------------- internals

    def screenshot(self, path: str | Path) -> Path:
        """Saves an image of the current screen.

        This is not a screen capture — there is no screen. It is the browser's
        rendering engine drawing into memory on request and handing us the PNG
        bytes. It works exactly the same headless.
        """
        if self.session is None or self.session.page is None:
            raise RuntimeError("no run open")
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.session.page.screenshot(path=str(p))
        return p

    def _is_terminal(self) -> bool:
        assert self.session is not None and self.session.page is not None
        return self.session.page.evaluate("() => window.__pk_point()") == "terminal"

    def _settle(self, timeout_s: float = 90.0) -> dict[str, Any]:
        """Runs through everything that is not a choice, then returns the state.

        The loop lives in the page (`__pk_settle`) and is driven in ONE call.
        The previous version made three round-trips per iteration and slept
        100 ms between them, so a battle spent most of its time with Python
        waiting on a fixed tick.

        It is deliberately not a `wait_for_function` predicate: that pumps an
        unpredictable number of times, and since pumping clicks things, the
        engine ends up consuming its seeded RNG in a different order and the
        same seed stops replaying the same run.
        """
        assert self.session is not None and self.session.page is not None
        settled = self.session.page.evaluate(
            "ms => window.__pk_settle(ms)", timeout_s * 1000
        )
        state = self.state()
        if not settled:
            state["stalled"] = True
        return state
