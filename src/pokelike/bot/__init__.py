"""The bots.

A bot is one thing: given the state, it says which action to take. Two places
hold them, and the split is not arbitrary.

**`bots/`, at the root of the repo, holds the bots.** One folder each, carrying
its own code and its own weights, prompts or tables. That is where yours goes,
and where every submitted one lives:

    bots/<name>/
    ├── bot.py        one class inheriting from Bot, self-contained
    ├── artifacts/    whatever it needs to play
    └── result.json   what the benchmark measured

**This package holds only what runs them**: the abstract `Bot` every bot
implements, and `RandomBot`, which is the baseline everything is measured
against and has to exist even in a checkout with no `bots/` folder at all.

    uv run pokelike new-bot mine     # creates bots/mine/
    uv run pokelike bot --bot mine
    uv run pokelike bench --bot mine

Nothing here is imported by name from a registry any more. A bot is a directory,
so someone can hand you one by handing you a directory.
"""

from __future__ import annotations

from .base import Bot
from .llm import LLMBot
from .random_bot import RandomBot

# The baseline lives in the package rather than only in `bots/random/` because
# `compare()` defaults to it: measuring against random must work in a checkout
# where `bots/` is empty, missing, or holds nothing but the bot being written.
BASELINE = "random"


def available() -> list[str]:
    """Every bot that can be built, from `bots/` plus the built-in baseline."""
    from .catalogue import available as on_disk

    return sorted({*on_disk(), BASELINE})


def resolve(name: str) -> str:
    """The full name of the bot `name` refers to.

    An exact name always wins. Failing that, a unique prefix is accepted, so
    `--bot sarsa-v` finds `sarsa-v2` — but `--bot sarsa` with both versions on
    disk is an ERROR naming them, not a guess. Picking one silently is how you
    benchmark a bot for an afternoon and report the wrong one: the two share a
    name precisely because they are variants of the same idea, so the result
    would look entirely plausible.
    """
    from .catalogue import available as on_disk
    from .catalogue import slugify

    slug = slugify(name)
    names = {*on_disk(), BASELINE}
    if slug in names:
        return slug

    matches = sorted(n for n in names if n.startswith(slug))
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise KeyError(
            f"'{name}' is ambiguous: {', '.join(matches)}\n"
            f"Name the one you mean."
        )
    raise KeyError(
        f"unknown bot '{name}' — available: {', '.join(sorted(names))}\n"
        f"Start a new one with:  uv run pokelike new-bot {slug}"
    )


def create(name: str, seed: int = 0) -> Bot:
    """Builds a bot by name: a folder in `bots/`, or the built-in baseline."""
    from .catalogue import available as on_disk
    from .catalogue import load

    full = resolve(name)
    if full in on_disk():
        return load(full, seed=seed)
    return RandomBot(seed=seed)


__all__ = ["Bot", "LLMBot", "RandomBot", "BASELINE",
           "available", "create", "resolve"]
