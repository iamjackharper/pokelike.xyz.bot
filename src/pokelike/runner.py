"""Playing one run with a bot, in one place.

This loop used to exist three times — in `bench.py`, in the CLI, and in the
prompt comparison — which is the kind of duplication that does not announce
itself. Add a hook to `Bot` and you update two of the three copies; the third
quietly stops calling it, and nothing fails, it just does less.

It lives in the package rather than in `experiments/` because the package needs
it too: the benchmark and the `bot` command are built on it.
"""

from __future__ import annotations

from typing import Any

from .core.game import Game


def play_run(
    game: Game,
    bot: Any,
    seed: int,
    max_steps: int = 400,
    on_step=None,
) -> dict[str, Any]:
    """Plays one run start to finish and returns what happened.

    `on_step(obs, steps)` is called before each decision, which is how the CLI
    saves a screenshot per turn without this function knowing what a screenshot
    is.

    The metrics come from `last_alive` rather than the final observation on
    purpose: at game over the engine wipes `state`, so the team and the badge
    count are gone by the time the run ends.
    """
    obs = game.reset(seed=seed)
    bot.on_start(seed)

    while not obs.get("done") and obs.get("actions") and game.steps < max_steps:
        if on_step:
            on_step(obs, game.steps)
        obs = game.step(bot.choose(obs))

    score = game.score() or {}
    bot.on_end(obs, score)

    breakdown = score.get("breakdown") or {}
    alive = game.last_alive or {}
    return {
        "seed": seed,
        "steps": game.steps,
        "score": score.get("points_no_time"),
        "score_raw": score.get("points"),
        "badges": (alive.get("run") or {}).get("badges", 0),
        "maps": breakdown.get("mapsCleared", 0),
        "kos": breakdown.get("enemiesKO", 0),
        "faints": breakdown.get("faints", 0),
        "ending": obs.get("screen"),
        "team": alive.get("team") or [],
        "final_state": obs,
        "score_detail": score,
    }
