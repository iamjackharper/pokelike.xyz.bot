"""What a bot actually receives, described from a real observation.

Hand-written documentation of a data structure goes stale the first time someone
adds a field and forgets the doc. This captures a live state instead and prints
the reference from it, so `pokelike schema` can never describe a game that no
longer exists.

    pokelike schema              # human readable reference
    pokelike schema --json       # a real observation, for poking at
    pokelike schema --markdown   # regenerates docs/STATE.md
"""

from __future__ import annotations

import json
from typing import Any

# What each field means. Anything present in a real observation but missing from
# here is reported as undocumented, which is the point: the check runs every time
# the reference is printed.
FIELDS = {
    "screen": "which screen you are on: map-screen, catch-screen, item-equip-modal, ...",
    "layer": "'screen' or 'modal' — modals are choices too, not decoration",
    "steps": "how many decisions this run has taken",
    "seed": "the run's seed; the same seed replays the same run",
    "done": "True when the run is over",
    "run": "run-wide facts: map index, badges, whether anyone has fainted",
    "team": "your Pokemon, in order. Everything about them",
    "bag": "item names you are carrying",
    "map": "the whole board: nodes, edges, where you stand",
    "stats": "the engine's cumulative counters, updated after every battle",
    "actions": "THE LEGAL MOVES. choose() returns an index into this list",
    "stalled": "only present if the engine stopped responding (should never happen)",
}

RUN_FIELDS = {
    "badges": "gym badges earned. This is the progression metric in Story mode",
    "map": "which map you are on, 0-indexed",
    "run_seed": "the engine's internal seed for this run",
    "max_team_size": "high-water mark of team size, NOT a limit (the limit is 6)",
    "anyone_fainted": "whether anything has fainted this run",
    "items_this_run": "items picked up",
    "elite": "Elite Four progress",
    "nuzlocke": "whether nuzlocke rules are on",
    "finished": "engine's own end-of-run flag",
}

TEAM_FIELDS = {
    "name": "species name, e.g. 'Bulbasaur'",
    "species_id": "national dex number",
    "level": "current level",
    "hp": "current HP",
    "max_hp": "maximum HP. hp/max_hp is what tells you if it is in danger",
    "types": "list of types, e.g. ['Grass', 'Poison'] — this decides battles",
    "base_stats": "hp, atk, def, speed, special, spdef",
    "item": "held item name, or null",
    "shiny": "whether it is shiny (worth points at the end)",
    "move_tier": "which tier of moves it knows",
    "mega_stone": "held mega stone, or null",
    "uid": "unique id within the run",
}

MAP_FIELDS = {
    "nodes": "every node: id, kind, layer, col, accessible, visited, revealed",
    "edges": "[from, to] pairs. This is how you know where a choice leads",
    "current": "id of the node you are standing on",
}

NODE_KINDS = {
    "start": "where the map begins",
    "catch": "adds a Pokemon to your team",
    "battle": "one wild Pokemon",
    "trainer": "1 Pokemon on map 0, 2 on maps 1-2, 3 from map 3 onwards",
    "item": "pick one of three items",
    "pokecenter": "restores HP",
    "question": "unknown until you enter it (shown as `unknown` in logs)",
    "boss": "the gym leader at the bottom of the map",
    "trade": "trade a Pokemon",
    "move_tutor": "teach a move",
    "pokemart": "buy something",
    "shiny": "a shiny encounter",
}


def describe(obs: dict[str, Any]) -> str:
    """The human-readable reference, built from a real observation."""
    out: list[str] = []
    add = out.append

    add("=" * 78)
    add("  WHAT A BOT RECEIVES")
    add("=" * 78)
    add("")
    add("  choose(state) -> int      returns an index into state['actions']")
    add("")
    add("  One state, not a history. The history that matters is already inside:")
    add("  every node carries `visited`, and `stats` are cumulative from the start")
    add("  of the run.")
    add("")

    add("-" * 78)
    add("TOP LEVEL")
    add("-" * 78)
    for k in sorted(obs):
        doc = FIELDS.get(k, "*** UNDOCUMENTED — add it to schema.py ***")
        add(f"  {k:<12} {doc}")

    add("")
    add("-" * 78)
    add("state['actions']  —  THE ONLY THING YOU MUST UNDERSTAND")
    add("-" * 78)
    add("  Between 2 and 7 entries. They change every turn, and they are NOT stable")
    add("  by position: index 2 is a battle now and a catch next turn.")
    add("")
    add("  Two shapes:")
    add("")
    add("  a map move                      any other choice")
    add("    kind:  'node'                   kind:  'element'")
    add("    id:    'n3_1'                   idx:   2")
    add("    node:  'catch'                  label: 'Squirtle Lv. 5 WATER ...'")
    add("    layer: 3                        layer: 'catch-screen'")
    add("    col:   1")
    add("")
    for a in (obs.get("actions") or [])[:3]:
        add(f"  real: {json.dumps(a)}")

    add("")
    add("  node kinds you will meet:")
    for k, v in NODE_KINDS.items():
        add(f"    {k:<12} {v}")

    add("")
    add("-" * 78)
    add("state['run']")
    add("-" * 78)
    for k in sorted(obs.get("run") or {}):
        add(f"  {k:<16} {RUN_FIELDS.get(k, '*** UNDOCUMENTED ***')}")

    add("")
    add("-" * 78)
    add("state['team'][i]")
    add("-" * 78)
    team = obs.get("team") or []
    for k in sorted(team[0]) if team else []:
        add(f"  {k:<14} {TEAM_FIELDS.get(k, '*** UNDOCUMENTED ***')}")

    add("")
    add("-" * 78)
    add("state['map']")
    add("-" * 78)
    for k in sorted(obs.get("map") or {}):
        add(f"  {k:<10} {MAP_FIELDS.get(k, '*** UNDOCUMENTED ***')}")
    add("")
    add("  Picking a node CLOSES every other node on that layer, forever. Use")
    add("  `edges` to see where a choice leads before taking it.")

    add("")
    add("-" * 78)
    add("state['stats']  —  the engine's own counters, for building a reward")
    add("-" * 78)
    for k in sorted(obs.get("stats") or {}):
        add(f"    {k}")
    add("")
    add("  Cumulative and updated after every battle, so a per-step reward is the")
    add("  difference between two consecutive observations.")

    add("")
    add("-" * 78)
    add("WHAT IS NOT IN HERE")
    add("-" * 78)
    add("  * which item you were offered and refused on a node you skipped")
    add("  * what a '?' node will turn into, before you enter it")
    add("  * the enemy team, before the battle starts")
    add("  A human player does not know these either.")
    add("")
    add("  Also absent on purpose: any reward. Reward is a training signal, and it")
    add("  belongs to whatever is learning, not to the state. See")
    add("  experiments/mdp/rewards.py.")
    return "\n".join(out)


def as_markdown(obs: dict[str, Any]) -> str:
    return (
        "# What a bot receives\n\n"
        "Generated by `pokelike schema --markdown` from a real observation, so it\n"
        "cannot describe a game that no longer exists. Regenerate it after any\n"
        "change to `core/bridge.js`.\n\n"
        "```\n" + describe(obs) + "\n```\n\n"
        "## A real observation\n\n"
        "```json\n" + json.dumps(obs, indent=1)[:4000] + "\n```\n"
    )


def capture(game, seed: int = 42, max_steps: int = 12) -> dict[str, Any]:
    """A mid-run observation, deep enough to show everything.

    A fresh run has no map and no team, and `stats` only appears after the first
    battle — which is exactly the field a bot author needs to build a reward. So
    we play on until the state has all three.
    """
    obs = game.reset(seed=seed)
    for _ in range(max_steps):
        if obs.get("done") or not obs.get("actions"):
            break
        if obs.get("map") and obs.get("team") and obs.get("stats"):
            break
        obs = game.step(0)
    return obs
