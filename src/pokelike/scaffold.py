"""Creating a new bot: `pokelike new-bot <name>`.

Writes a folder that already plays. That is the point — you can benchmark it
before changing a line, so when the number moves you know it moved because of
something you did.
"""

from __future__ import annotations

from pathlib import Path

from .bot.catalogue import BOTS, available, slugify

TEMPLATE = '''"""{title}

    uv run pokelike bot --bot {name} --runs 5 -d
    uv run pokelike bench --bot {name} --dry-run

A bot is one method: given the state, say which action to take. Everything else
-- starting the browser, applying the move, scoring the run -- is handled for you.

This one heals when somebody is hurt and otherwise walks towards trainers, which
is worth more than random and not much more. Replace it.

WHAT YOU GET TO LOOK AT
`state` is one dict, not a history: what history matters is already inside it.
Every map node carries `visited`, and `stats` are cumulative from the start.

    uv run pokelike schema        prints the whole reference from a live game

THE ONE THING THAT CATCHES EVERYONE
`state["actions"]` is renumbered every turn. Index 2 is a battle now and a catch
next turn, so nothing can be decided by position -- look at what each entry is.

KEEP THIS FILE SELF-CONTAINED
Whatever it needs beyond the `pokelike` package goes in `artifacts/` beside it.
If you train something, freeze the state encoding HERE rather than importing it
from your training code: otherwise improving that code silently changes what
your own past scores meant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pokelike.bot.base import Bot

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"


class {cls}(Bot):
    name = "{name}"

    def choose(self, state: dict[str, Any]) -> int:
        """Which action to take, as an index into state["actions"]."""
        team = state.get("team") or []
        hurt = any(p["hp"] / p["max_hp"] < 0.5 for p in team if p["max_hp"])

        for i, a in enumerate(state["actions"]):
            if hurt and a.get("node") == "pokecenter":
                return i
        for i, a in enumerate(state["actions"]):
            if a.get("node") == "trainer":
                return i
        return 0

    def explain(self) -> str:
        """One line under each decision in the log. Optional."""
        return ""

    # Other optional hooks, all of them safe to ignore:
    #
    #   rearrange(state) -> (a, b) | None   who leads the next battle. Free: it
    #                                       does not consume the turn
    #   on_start(seed) / on_end(state, score)   for a bot with memory
    #   artifacts() -> [Artifact]           weights and config to record beside
    #                                       the result when you benchmark
'''

README = '''# {name}

_One line on what this bot does and how it decides._

```bash
uv run pokelike bot --bot {name} --runs 5 -d
uv run pokelike bench --bot {name} --dry-run
```

| | |
|---|---|
| how it works | |
| what it scored | run the benchmark and fill this in |
| what was tried and dropped | |
'''


def new_bot(name: str, root: Path | None = None) -> Path:
    """Creates `bots/<name>/`, or explains why it cannot."""
    slug = slugify(name)
    base = Path(root) if root else BOTS
    d = base / slug

    if d.exists():
        raise FileExistsError(
            f"{d} already exists. Pick another name, or work on the one that is "
            f"there:\n  uv run pokelike bot --bot {slug} --runs 5 -d"
        )
    if slug in available(base):
        raise FileExistsError(f"a bot named '{slug}' already exists")

    cls = "".join(part.capitalize() for part in slug.split("-")) + "Bot"
    (d / "artifacts").mkdir(parents=True)
    (d / "bot.py").write_text(
        TEMPLATE.format(name=slug, cls=cls, title=f"{slug}: a starting point."),
        encoding="utf-8",
    )
    (d / "README.md").write_text(README.format(name=slug), encoding="utf-8")
    # Git does not track an empty directory, and a bot with no artifacts is
    # normal — a rules bot needs none — so leave something to keep the shape.
    (d / "artifacts" / ".gitkeep").write_text("", encoding="utf-8")
    return d
