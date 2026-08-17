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


def short_label(a: dict[str, Any]) -> str:
    """A compact name for an action, for logs and traces.

    Labels that carry row context read like "EQUIP — Ponyta Lv8 — empty — EQUIP".
    The informative half is the context, not the button word, so keep both: five
    identical "EQUIP" entries in a log tell you nothing about what was chosen.
    """
    if a.get("kind") == "node":
        return a["node"]
    label = (a.get("label") or "").strip()
    if "—" in label:
        parts = [p.strip() for p in label.split("—")]
        return f"{parts[0]}:{parts[1]}"[:38]
    return label[:34] or f"slot{a.get('idx', 0)}"


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
    trace: list[dict[str, Any]] = []

    while not obs.get("done") and obs.get("actions") and game.steps < max_steps:
        if on_step:
            on_step(obs, game.steps)

        options = list(obs["actions"])
        chosen = bot.choose(obs)

        # Recorded for every bot alike, in the shared loop rather than in each
        # bot, so the log means the same thing whatever is playing.
        run = obs.get("run") or {}
        team = obs.get("team") or []
        trace.append({
            "step": game.steps,
            "screen": obs.get("screen"),
            "map": run.get("map"),
            "badges": run.get("badges"),
            "team": [f"{p['name']} L{p['level']} {p['hp']}/{p['max_hp']}" for p in team],
            "options": [short_label(a) for a in options],
            "chosen": chosen,
            "chosen_label": short_label(options[chosen]) if 0 <= chosen < len(options) else "?",
            "why": (bot.explain() or "").strip(),
        })

        obs = game.step(chosen)

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
        "trace": trace,
    }
