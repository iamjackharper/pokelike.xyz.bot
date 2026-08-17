"""Builds the fingerprint of a played run.

This is the heart of the regression suite. The fingerprint holds only data that
comes **from the game engine** — screen ids, node types, Pokemon names, scores —
never text we write ourselves. That is deliberate: our own wording can be
translated or reworded, the engine's data cannot change without a real
behavioural regression.

So the same golden file stays valid across a full translation of this codebase,
and any difference in it is a genuine bug.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).parent / "golden" / "runs.json"


def policy_fixed(state: dict[str, Any]) -> int:
    """Always the first legal action. Fully deterministic, no RNG involved."""
    return 0


def policy_cycling(state: dict[str, Any]) -> int:
    """Cycles through the options, so the run does not always hug one branch."""
    return state["steps"] % len(state["actions"])


POLICIES = {"fixed": policy_fixed, "cycling": policy_cycling}


def _stable_action(a: dict[str, Any]) -> str:
    """A label that survives translation: it comes from the game, not from us."""
    if a.get("kind") == "node":
        return f"{a['id']}:{a['node']}"
    # `label` is the button text rendered by the game itself (English).
    return f"el{a['idx']}:{(a.get('label') or '')[:40]}"


def fingerprint(game, seed: int, policy: str, max_steps: int = 120) -> dict[str, Any]:
    """Plays one run and returns its fingerprint."""
    choose = POLICIES[policy]
    obs = game.reset(seed=seed)
    trace: list[str] = []

    while not obs.get("done") and obs.get("actions") and game.steps < max_steps:
        i = choose(obs)
        trace.append(f"{obs['screen']}|{len(obs['actions'])}|{_stable_action(obs['actions'][i])}")
        obs = game.step(i)

    s = game.score() or {}
    alive = game.last_alive or obs
    return {
        "seed": seed,
        "policy": policy,
        "steps": game.steps,
        "final_screen": obs.get("screen"),
        "points": s.get("points_no_time"),
        "breakdown": s.get("breakdown"),
        "team": [
            {"name": m["name"], "level": m["level"], "hp": m["hp"], "max_hp": m["max_hp"]}
            for m in (alive.get("team") or [])
        ],
        "trace": trace,
    }


def load_golden() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def save_golden(data: dict[str, Any]) -> None:
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


# Runs recorded in the golden file. Deliberately few: each costs about ten
# seconds of wall clock.
CASES = [(1, "fixed"), (2, "fixed"), (3, "cycling"), (7, "cycling")]
