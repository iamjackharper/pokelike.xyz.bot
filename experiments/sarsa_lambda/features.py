"""Turning (state, action) into a feature vector.

This is the part that matters. Tabular Dyna-Q is blind by construction: it
compresses the state to six numbers and keys actions by type, so on the starter
screen it learns Q values of 6.3, 6.2, 6.3 — three indistinguishable slots where
a player sees Bulbasaur, Charmander and Squirtle. No amount of extra episodes
fixes that, because the information never reaches the table.

Linear function approximation (Sutton & Barto, chapter 9) lets us hand the agent
what it was missing:

    q̂(s, a, w) = wᵀ x(s, a)

Two consequences beyond seeing more. Features generalise, so a lesson learned
about "catching something that adds a type I lack" transfers to every such
choice rather than to one table cell — which matters enormously here, because
every real step costs 0.7 seconds of browser. And actions are described rather
than named, so five EQUIP buttons are five different vectors instead of one
collapsed key.

The features are deliberately hand-made and few. With ~15 s per episode there is
no budget for learning a representation from scratch, so the domain knowledge
goes in by hand and the agent learns the weights.
"""

from __future__ import annotations

import re
from typing import Any

TYPES = {
    "NORMAL", "FIRE", "WATER", "ELECTRIC", "GRASS", "ICE", "FIGHTING", "POISON",
    "GROUND", "FLYING", "PSYCHIC", "BUG", "ROCK", "GHOST", "DRAGON", "DARK",
    "STEEL", "FAIRY",
}

# Node kinds worth a feature of their own. Anything rarer falls into `other`.
NODE_KINDS = [
    "catch", "battle", "trainer", "item", "pokecenter", "question",
    "move_tutor", "trade", "boss", "pokemart", "shiny", "other",
]

SCREENS = [
    "catch-screen", "starter-screen", "item-screen", "item-equip-modal",
    "swap-screen", "trainer-screen", "other-screen",
]

RE_LEVEL = re.compile(r"Lv\.?\s*(\d+)")
RE_POWER = re.compile(r"(\d+)\s*PWR")
RE_HP = re.compile(r"\bHP\s+(\d+)")
RE_ATK = re.compile(r"\bATK\s+(\d+)")
RE_SPA = re.compile(r"SP\.A\s+(\d+)")
RE_DEF = re.compile(r"\bDEF\s+(\d+)")


def parse_pokemon(label: str) -> dict[str, Any]:
    """Pull what matters out of a Pokemon card's text.

    The catch screen renders 'Psyduck Lv. 4 WATER SP.A 10 SPE 9 HP 18 DEF 8 ...'.
    All of it is on screen and none of it reached the tabular agent.
    """
    up = label.upper()
    types = [t for t in TYPES if re.search(rf"\b{t}\b", up)]
    lvl = RE_LEVEL.search(label)
    pwr = RE_POWER.search(label)
    hp = RE_HP.search(label)
    atk = RE_ATK.search(label) or RE_SPA.search(label)
    dfn = RE_DEF.search(label)
    return {
        "types": types,
        "level": int(lvl.group(1)) if lvl else 0,
        "power": int(pwr.group(1)) if pwr else 0,
        "hp": int(hp.group(1)) if hp else 0,
        "atk": int(atk.group(1)) if atk else 0,
        "def": int(dfn.group(1)) if dfn else 0,
        "shiny": "★" in label or "SHINY" in up,
    }


def _team_types(team: list[dict]) -> set[str]:
    return {t.upper() for p in team for t in (p.get("types") or [])}


def _hp_fracs(team: list[dict]) -> list[float]:
    return [p["hp"] / p["max_hp"] for p in team if p.get("max_hp")]


def _depth_frac(state: dict[str, Any]) -> float:
    m = state.get("map")
    if not m or not m.get("current"):
        return 0.0
    layers = [n["layer"] for n in m["nodes"]]
    cur = next((n["layer"] for n in m["nodes"] if n["id"] == m["current"]), 0)
    return cur / max(layers) if layers and max(layers) else 0.0


def _leads_to(state: dict[str, Any], node_id: str) -> list[str]:
    m = state.get("map") or {}
    by_id = {n["id"]: n for n in m.get("nodes", [])}
    return [by_id[t]["kind"] for f, t in m.get("edges", []) if f == node_id and t in by_id]


# The names are the vector's index order. Keeping them explicit means a trained
# weight vector can be read and argued with, which is most of the point of a
# linear model.
def feature_names() -> list[str]:
    names = [
        "bias", "team_size", "min_hp", "mean_hp", "map_index", "depth",
        "badges", "any_fainted", "n_actions",
    ]
    names += [f"node:{k}" for k in NODE_KINDS]
    names += [f"node:{k}*deep" for k in NODE_KINDS]
    names += [f"node:{k}*hurt" for k in NODE_KINDS]
    names += [f"node:{k}*small_team" for k in NODE_KINDS]
    names += ["leads_to_heal", "leads_to_catch", "leads_to_boss", "leads_dead_end"]
    names += [f"screen:{s}" for s in SCREENS]
    names += [
        "mon_new_type", "mon_level_rel", "mon_power", "mon_bulk", "mon_atk",
        "mon_shiny", "mon_best_stats",
        "equip_on_strongest", "equip_on_weakest", "swap_out_weakest",
        "is_skip", "is_cancel", "is_bag",
    ]
    return names


N_FEATURES = len(feature_names())


def features(state: dict[str, Any], action: dict[str, Any]) -> dict[int, float]:
    """Sparse x(s, a): index -> value. Only non-zero entries."""
    names = _NAME_INDEX
    x: dict[int, float] = {}

    def put(name: str, value: float = 1.0) -> None:
        if value:
            x[names[name]] = value

    run = state.get("run") or {}
    team = state.get("team") or []
    fracs = _hp_fracs(team)
    min_hp = min(fracs) if fracs else 0.0
    mean_hp = sum(fracs) / len(fracs) if fracs else 0.0
    depth = _depth_frac(state)
    small_team = 1.0 - min(len(team), 6) / 6

    put("bias")
    put("team_size", min(len(team), 6) / 6)
    put("min_hp", min_hp)
    put("mean_hp", mean_hp)
    put("map_index", min(run.get("map") or 0, 8) / 8)
    put("depth", depth)
    put("badges", min(run.get("badges") or 0, 8) / 8)
    put("any_fainted", 1.0 if run.get("anyone_fainted") else 0.0)
    put("n_actions", len(state.get("actions") or []) / 7)

    if action.get("kind") == "node":
        kind = action["node"] if action["node"] in NODE_KINDS else "other"
        put(f"node:{kind}")
        put(f"node:{kind}*deep", depth)
        put(f"node:{kind}*hurt", 1.0 - min_hp)
        put(f"node:{kind}*small_team", small_team)

        ahead = _leads_to(state, action["id"])
        put("leads_to_heal", 1.0 if "pokecenter" in ahead else 0.0)
        put("leads_to_catch", 1.0 if "catch" in ahead else 0.0)
        put("leads_to_boss", 1.0 if "boss" in ahead else 0.0)
        put("leads_dead_end", 1.0 if not ahead else 0.0)
        return x

    screen = action.get("layer") if action.get("layer") in SCREENS else "other-screen"
    put(f"screen:{screen}")
    label = action.get("label") or ""
    low = label.lower()

    put("is_skip", 1.0 if "skip" in low else 0.0)
    put("is_cancel", 1.0 if "cancel" in low else 0.0)
    put("is_bag", 1.0 if "keep in bag" in low else 0.0)

    if screen in ("catch-screen", "starter-screen"):
        mon = parse_pokemon(label)
        if mon["types"]:
            have = _team_types(team)
            put("mon_new_type", 1.0 if any(t not in have for t in mon["types"]) else 0.0)
        levels = [p["level"] for p in team] or [mon["level"] or 1]
        put("mon_level_rel", min(2.0, mon["level"] / max(1, sum(levels) / len(levels))) / 2)
        put("mon_power", min(mon["power"], 100) / 100)
        put("mon_bulk", min(mon["hp"], 40) / 40)
        put("mon_atk", min(mon["atk"], 40) / 40)
        put("mon_shiny", 1.0 if mon["shiny"] else 0.0)
        # Which of the options on offer is objectively the beefiest.
        rivals = [parse_pokemon(o.get("label") or "") for o in state["actions"]]
        totals = [r["hp"] + r["atk"] + r["def"] for r in rivals]
        mine = mon["hp"] + mon["atk"] + mon["def"]
        put("mon_best_stats", 1.0 if totals and mine >= max(totals) else 0.0)
        return x

    if screen in ("item-equip-modal", "swap-screen") and team:
        # These screens list the team, so the option's position is the member.
        idx = action.get("idx", 0)
        if idx < len(team):
            atk_of = [p.get("base_stats", {}).get("atk", 0) for p in team]
            hp_of = [p["hp"] for p in team]
            strongest = max(range(len(team)), key=lambda i: atk_of[i])
            weakest = min(range(len(team)), key=lambda i: (team[i]["level"], hp_of[i]))
            put("equip_on_strongest", 1.0 if idx == strongest else 0.0)
            put("equip_on_weakest", 1.0 if idx == weakest else 0.0)
            # On the swap screen the listed Pokemon is the one RELEASED, so
            # releasing the weakest is the good move and releasing the best is
            # the mistake. Same list, opposite meaning: see state["prompt"].
            if screen == "swap-screen":
                put("swap_out_weakest", 1.0 if idx == weakest else 0.0)
    return x


_NAME_INDEX = {n: i for i, n in enumerate(feature_names())}
