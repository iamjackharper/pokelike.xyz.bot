"""Submissions: what a bot leaves behind so its result can be trusted.

A leaderboard is only worth reading if an entry says exactly what produced it.
That means three things travel together and are never allowed to drift apart:

    the result   what it scored, on which seeds, against which game build
    the bot      the source that was actually run
    the artifacts  weights, prompts, model names, hyperparameters

This module builds that folder, and it does so from data the bot itself
declares. Nothing is left to a convention someone might forget: if it is not in
`Bot.artifacts()` it does not get archived, and if it is, it gets hashed.

    leaderboard/
    ├── index.json                    generated from the entries
    └── entries/
        └── <slug>-<hash>/
            ├── submission.json       metadata, results, artifact manifest
            ├── bot.py                a copy of the bot that ran
            └── artifacts/
                ├── manifest.json
                └── ...               whatever the bot declared

The folder name carries a short hash over the bot source, the declared
artifacts and the seed list. That makes an entry immutable by construction: a
tweaked bot produces a different folder rather than silently overwriting the
old result, and nobody can swap the weights while keeping the score.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The kinds of thing a bot can leave behind. Open on purpose: an unknown kind is
# archived anyway, it just is not understood by the index.
KINDS = (
    "weights-json",    # a tabular policy small enough to live in the repo
    "weights-file",    # a local binary (npz, pt, safetensors)
    "weights-remote",  # url + sha256 + how to load it (Hugging Face, a release)
    "prompt",          # the prompts of an LLM bot
    "model-ref",       # provider, model name, temperature, version
    "config",          # the hyperparameters it was trained with
    "code-ref",        # the git commit of the training code
    "notes",           # anything else worth keeping
)

# Above this, a file belongs somewhere else and should be referenced instead of
# committed. Git repositories are not artifact stores.
MAX_INLINE_BYTES = 5 * 1024 * 1024


@dataclass
class Artifact:
    """One thing a bot wants archived alongside its result.

    Exactly one of `path`, `data` or `text` carries the content:
      path  copy this existing file in
      data  serialise this object as JSON
      text  write this string as-is
    """

    name: str
    kind: str
    description: str = ""
    path: Path | None = None
    data: Any = None
    text: str | None = None

    def write_into(self, folder: Path) -> dict[str, Any]:
        """Materialises the artifact and returns its manifest entry."""
        target = folder / self.name
        target.parent.mkdir(parents=True, exist_ok=True)

        if self.path is not None:
            src = Path(self.path)
            if not src.is_file():
                raise FileNotFoundError(f"artifact '{self.name}' points at {src}, which does not exist")
            size = src.stat().st_size
            if size > MAX_INLINE_BYTES:
                raise ValueError(
                    f"artifact '{self.name}' is {size / 1e6:.1f} MB, over the "
                    f"{MAX_INLINE_BYTES / 1e6:.0f} MB limit for files kept in the repo.\n"
                    "Upload it somewhere (a GitHub release, Hugging Face) and declare a "
                    "'weights-remote' artifact with the url and its sha256 instead."
                )
            shutil.copy2(src, target)
        elif self.data is not None:
            target.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        elif self.text is not None:
            target.write_text(self.text, encoding="utf-8")
        else:
            raise ValueError(f"artifact '{self.name}' has no content: set path, data or text")

        blob = target.read_bytes()
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }


# ------------------------------------------------------------------- helpers


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "bot"


def _bot_source(bot: Any) -> tuple[str, str]:
    """The source file of the bot's class, so the entry keeps what actually ran."""
    try:
        f = Path(inspect.getfile(type(bot)))
        return f.name, f.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — a bot defined in a REPL has no file
        return "bot.py", "# source not available (bot defined outside a file)\n"


def entry_id(name: str, source: str, manifest: list[dict], seeds: list[int]) -> str:
    """`<slug>-<hash>`, where the hash covers everything that defines the run."""
    h = hashlib.sha256()
    h.update(source.encode("utf-8"))
    for m in sorted(manifest, key=lambda x: x["name"]):
        h.update(m["name"].encode("utf-8"))
        h.update(m["sha256"].encode("utf-8"))
    h.update(json.dumps(seeds).encode("utf-8"))
    return f"{slugify(name)}-{h.hexdigest()[:6]}"


# -------------------------------------------------------------------- writing


def write_entry(root: Path, result: dict[str, Any], bot: Any) -> Path:
    """Creates the whole entry folder. Returns its path.

    Built in a temporary folder first, because the entry id depends on the
    hashes of the artifacts, which are only known once they are written.
    """
    entries = Path(root) / "entries"
    entries.mkdir(parents=True, exist_ok=True)

    staging = entries / f".staging-{slugify(result['bot'])}"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "artifacts").mkdir(parents=True)

    declared: list[Artifact] = list(getattr(bot, "artifacts", lambda: [])() or [])
    for a in declared:
        if a.kind not in KINDS:
            print(f"  note: artifact '{a.name}' has an unrecognised kind '{a.kind}', "
                  f"archiving it anyway")
    manifest = [a.write_into(staging / "artifacts") for a in declared]

    filename, source = _bot_source(bot)
    (staging / "bot.py").write_text(source, encoding="utf-8")

    eid = entry_id(result["bot"], source, manifest, result.get("seeds") or [])
    document = {
        **result,
        "id": eid,
        "bot_source_file": filename,
        "artifacts": manifest,
    }
    (staging / "submission.json").write_text(
        json.dumps(document, indent=1), encoding="utf-8"
    )
    (staging / "artifacts" / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8"
    )

    final = entries / eid
    if final.exists():
        shutil.rmtree(final)
    staging.rename(final)
    return final


# -------------------------------------------------------------------- reading


def load_entries(root: Path) -> list[dict[str, Any]]:
    entries = Path(root) / "entries"
    if not entries.is_dir():
        return []
    out = []
    for f in sorted(entries.glob("*/submission.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            print(f"  warning: {f} is not valid JSON, skipping")
    return out


def build_index(root: Path) -> dict[str, Any]:
    """Regenerates index.json from whatever entries are on disk."""
    entries = load_entries(root)
    rows = []
    for e in entries:
        s = e.get("summary") or {}
        rows.append({
            "id": e.get("id"),
            "bot": e.get("bot"),
            "author": e.get("author"),
            "category": e.get("category"),
            "description": e.get("description"),
            "score_mean": s.get("score_mean"),
            "score_stdev": s.get("score_stdev"),
            "score_best": s.get("score_best"),
            "badges_mean": s.get("badges_mean"),
            "badges_best": s.get("badges_best"),
            "maps_mean": s.get("maps_mean"),
            "completed": s.get("completed"),
            "runs": s.get("runs"),
            "game": (e.get("game") or {}).get("sha256"),
            "artifacts": len(e.get("artifacts") or []),
        })
    # Ranked by badges, not by score. Badges are the game's own progression
    # counter in Story mode; the engine's score formula was written for the
    # Battle Tower and two of its terms (mapsCleared, winBonus) never fire here,
    # so it rewards fighting rather than getting further. See
    # experiments/env/rewards.py for the full story.
    rows.sort(key=lambda r: (
        r["badges_mean"] is None, -(r["badges_mean"] or 0), -(r["score_mean"] or 0)
    ))
    index = {"entries": rows}
    (Path(root) / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    # The README table is regenerated from the same data, in the same call. A
    # second command to run would be a second command to forget, and then the
    # table on the page and the entries on disk would disagree.
    render_readme(Path(root), index)
    return index


README_BEGIN = "<!-- BEGIN standings: generated by `pokelike leaderboard`, do not edit by hand -->"
README_END = "<!-- END standings -->"


def as_markdown(index: dict[str, Any]) -> str:
    """The standings as a markdown table.

    Ranked by badges. The engine's score formula was written for the Battle
    Tower and two of its six terms never fire in Story mode, so it rewards
    fighting rather than getting further — the score column is kept because a
    policy that scores badly while earning badges is telling you something, but
    it is not the ranking.
    """
    rows = index.get("entries") or []
    if not rows:
        return ("_No submissions yet._ Yours would be the first — see "
                "**How to submit** below.\n")

    out = [
        "| # | bot | author | how | runs | badges~ | badges+ | score~ | best | game |",
        "|--:|---|---|---|--:|--:|--:|--:|--:|---|",
    ]
    for i, r in enumerate(rows, 1):
        n = lambda k, d="-": r[k] if r.get(k) is not None else d  # noqa: E731
        # The bundle hash matters: scores from before and after an upstream game
        # update are not comparable, and without it a table mixes them silently.
        game = (r.get("game") or "")[:8] or "-"
        out.append(
            f"| {i} | **{r.get('bot') or '?'}** | {r.get('author') or '-'} "
            f"| {r.get('category') or '-'} | {n('runs', 0)} "
            f"| **{n('badges_mean')}** | {n('badges_best')} "
            f"| {n('score_mean')} | {n('score_best')} | `{game}` |"
        )
    out += [
        "",
        "Ranked by **badges**, the game's own progression counter. `badges~` is the "
        "mean over the standard 50 seeds and `badges+` the best single run. "
        "`game` is the sha256 prefix of the game bundle that was played: results "
        "under different hashes are not comparable.",
        "",
    ]
    return "\n".join(out)


def render_readme(root: Path, index: dict[str, Any]) -> Path | None:
    """Writes the standings into leaderboard/README.md, between the markers.

    Called whenever the index is rebuilt, so a submitted entry shows up in the
    table without anyone having to remember a second command — which means the
    pull request that adds an entry also carries the row for it.
    """
    readme = root / "README.md"
    if not readme.is_file():
        return None
    text = readme.read_text(encoding="utf-8")
    begin, end = text.find(README_BEGIN), text.find(README_END)
    if begin < 0 or end < 0:
        return None
    readme.write_text(
        text[:begin] + README_BEGIN + "\n\n" + as_markdown(index) + "\n" + text[end:],
        encoding="utf-8",
    )
    return readme


def format_table(index: dict[str, Any]) -> str:
    rows = index.get("entries") or []
    if not rows:
        return "no submissions yet"
    head = (f"{'bot':<20}{'category':>10}{'runs':>6}{'badge~':>8}{'badge+':>8}"
            f"{'score~':>9}{'stdev':>8}{'best':>7}{'done':>6}")
    out = [head, "-" * len(head)]
    for r in rows:
        out.append(
            f"{(r['bot'] or '')[:19]:<20}{(r['category'] or ''):>10}{r['runs'] or 0:>6}"
            f"{r['badges_mean'] if r['badges_mean'] is not None else '-':>8}"
            f"{r['badges_best'] if r.get('badges_best') is not None else '-':>8}"
            f"{r['score_mean'] if r['score_mean'] is not None else '-':>9}"
            f"{r['score_stdev'] if r['score_stdev'] is not None else '-':>8}"
            f"{r['score_best'] if r['score_best'] is not None else '-':>7}"
            f"{r['completed'] if r['completed'] is not None else '-':>6}"
        )
    return "\n".join(out)
