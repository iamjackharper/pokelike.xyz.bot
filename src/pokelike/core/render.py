"""Text rendering of the game state.

Everything here is rebuilt from `state`, a JavaScript object read as JSON. No
pixel is ever inspected: the map below is not read from an image, we draw it
ourselves from the nodes and edges.
"""

from __future__ import annotations

from typing import Any

ICONS = {
    "start": "@", "battle": "x", "trainer": "T", "catch": "o", "item": "i",
    "pokecenter": "+", "question": "?", "trade": "$", "move_tutor": "M",
    "boss": "B", "shiny": "*", "pokemart": "S", "mutation": "%",
    "evil_team": "E", "silver": "s", "legendary": "L",
}

LEGEND = (
    "@ start    x wild fight   T trainer   o catch    i item     + pokecenter\n"
    "? unknown  $ trade        M tutor      B boss   S shop     * shiny"
)


def map_view(m: dict[str, Any] | None) -> str:
    if not m:
        return "  (no map)"
    by_layer: dict[int, list[dict]] = {}
    for n in m["nodes"]:
        if not n["revealed"]:
            continue
        by_layer.setdefault(n["layer"], []).append(n)

    rows = []
    for layer in sorted(by_layer):
        cells = []
        for n in sorted(by_layer[layer], key=lambda x: x["col"]):
            ic = ICONS.get(n["kind"], ".")
            if n["id"] == m.get("current"):
                cells.append(f"[{ic}]")       # where you are now
            elif n["accessible"] and not n["visited"]:
                cells.append(f"<{ic}>")       # a legal move
            elif n["visited"]:
                cells.append(f" {ic}'")       # already done
            else:
                cells.append(f" {ic} ")
        rows.append(f"  layer {layer:>2} | " + " ".join(cells))
    return "\n".join(rows)


def team_view(team: list[dict] | None) -> str:
    if not team:
        return "  (empty team)"
    rows = []
    for i, p in enumerate(team):
        filled = round((p["hp"] / p["max_hp"]) * 10) if p["max_hp"] else 0
        bar = "#" * max(0, filled) + "." * max(0, 10 - filled)
        item = f"  [{p['item']}]" if p.get("item") else ""
        shiny = " *" if p.get("shiny") else ""
        rows.append(
            f"  {i}. {p['name']:<13}Lv{p['level']:>2}  {bar} {p['hp']:>3}/{p['max_hp']:<3}"
            f"  {'/'.join(p.get('types') or [])}{item}{shiny}"
        )
    return "\n".join(rows)


def actions_view(actions: list[dict]) -> str:
    if not actions:
        return "  (no actions)"
    rows = []
    for i, a in enumerate(actions):
        if a["kind"] == "node":
            rows.append(f"  [{i}] go to node {a['id']:<6} ({a['node']})")
        else:
            rows.append(f"  [{i}] {a['label']}")
    return "\n".join(rows)


def screen(obs: dict[str, Any], with_legend: bool = False) -> str:
    """The whole turn as text."""
    run = obs.get("run") or {}
    head = (
        f"step {obs.get('steps', 0)}   screen: {obs.get('screen')}   "
        f"map {run.get('map', '-')}   badges {run.get('badges', '-')}"
    )
    parts = ["=" * 72, head, "=" * 72]
    if obs.get("prompt"):
        # What the screen is asking. Without it, "pick one of your team" is
        # ambiguous between promoting and releasing.
        parts += ["", f'  >> {obs["prompt"]}']
    parts += ["", "TEAM", team_view(obs.get("team"))]

    bag = obs.get("bag") or []
    if bag:
        parts += ["", "BAG", "  " + ", ".join(str(b) for b in bag)]

    if obs.get("map"):
        parts += ["", "MAP   [here]  <legal move>  x'=done", map_view(obs["map"])]
        if with_legend:
            parts += ["", LEGEND]

    parts += ["", "ACTIONS", actions_view(obs.get("actions") or [])]

    if obs.get("done"):
        parts += ["", ">>> RUN OVER <<<"]
    return "\n".join(parts)


def score_view(s: dict[str, Any] | None) -> str:
    if not s:
        return "score not available"
    b = s.get("breakdown") or {}
    st = s.get("stats") or {}
    rows = [
        f"SCORE: {s.get('points')}   (without time bonus: {s.get('points_no_time')})",
        "",
        f"  win bonus           {b.get('winBonus', 0):>6}",
        f"  enemies knocked out {b.get('enemiesKO', 0):>6}  (x5)",
        f"  own faints          {b.get('faints', 0):>6}  (x-10)",
        f"  maps cleared        {b.get('mapsCleared', 0):>6}  (x50)",
        f"  legendaries         {b.get('legendaries', 0):>6}  (x20)",
        f"  shinies             {b.get('shinies', 0):>6}  (x20)",
        f"  time bonus          {b.get('timeBonus', 0):>6}",
        "",
        f"  battles won         {st.get('battlesWon', 0):>6}",
        f"  catches             {st.get('catches', 0):>6}",
        f"  damage dealt        {st.get('totalDamageDealt', 0):>6}",
        f"  damage taken        {st.get('totalDamageTaken', 0):>6}",
        f"  critical hits       {st.get('critHits', 0):>6}",
        f"  highest level       {st.get('highestLevel', 0):>6}",
    ]
    return "\n".join(rows)


def trace_line(t: dict[str, Any]) -> str:
    """One decision on one line. `>` marks what was taken, so no second column."""
    options = "  ".join(
        f"{'>' if i == t['chosen'] else ' '}{o}" for i, o in enumerate(t["options"])
    )
    return (f"  {t['step']:>3} {t['screen']:<17} b{t.get('badges', 0)} "
            f"m{t.get('map', 0)} | {options}")


def trace_view(trace: list[dict[str, Any]], detail: int = 1) -> str:
    """The log of a run.

    detail 1  one line per decision
    detail 2  a block per decision, with the bot's own explanation
    detail 3  and the team at every step

    Everything except the explanation is recorded by the shared run loop, so it
    reads the same whatever was playing. The explanation is empty for bots that
    have nothing to say — which is honest, not a gap.
    """
    if not trace:
        return "  (no decisions recorded)"
    if detail <= 1:
        return "\n".join(trace_line(t) for t in trace)
    with_team = detail >= 3
    out = []
    for t in trace:
        head = (f"  {t['step']:>3} | {t['screen']:<18} "
                f"map {t.get('map', '-')}  badges {t.get('badges', '-')}")
        out.append(head)
        if with_team and t.get("team"):
            out.append(f"      | team: {', '.join(t['team'])}")
        marked = [
            f"[{i}]{'*' if i == t['chosen'] else ' '}{o}"
            for i, o in enumerate(t["options"])
        ]
        out.append(f"      | {'  '.join(marked)}")
        out.append(f"      | -> {t['chosen_label']}")
        if t.get("why"):
            out.append(f"      |    {t['why'][:110]}")
        out.append("")
    return "\n".join(out)
