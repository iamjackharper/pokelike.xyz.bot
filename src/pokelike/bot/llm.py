"""A bot driven by an LLM, with an agentic loop and tools.

Everything it needs lives in this one file: configuration, prompts, tools, HTTP
call. No extra dependencies — it talks to an OpenAI-compatible endpoint using
`urllib` from the standard library.

Configuration comes from environment variables only (never keys in code):

    export FW_ENDPOINT="https://..."
    export FW_TOKEN="..."
    export MODEL_ID="..."            # optional
    pokelike bot --bot llm --runs 3

How a turn works: the model gets the situation as text and the numbered list of
actions. It may call read-only tools to dig deeper, and closes by calling
`play(index)`. If it does not within `max_rounds`, or anything goes wrong, we
fall back to a safe choice: **a run must never die because of the model**.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..core import render
from .base import Bot

# -------------------------------------------------------------------- prompts
#
# Prompts are swappable so they can be compared rather than argued about:
#
#     POKELIKE_LLM_STRATEGY=survivor pokelike bot --bot llm --runs 5
#
# What every prompt must get right, because it is easy to get wrong:
#
#   * BADGES ARE THE GOAL. The engine's score formula was written for the Battle
#     Tower and two of its terms never fire in Story mode, so telling the model
#     to chase "maps cleared" points it at something that is always zero. An
#     earlier version of this prompt did exactly that.
#   * Choosing a node CLOSES the others on that layer, forever.
#   * Trainers scale: 1 Pokemon on map 0, 2 on maps 1-2, 3 from map 3 onwards.
#     Read out of the bundle, not guessed.
#   * Battles resolve themselves. The model never picks a move.

RULES = """You are playing Pokelike, a Pokemon roguelike.

YOUR GOAL: earn as many gym badges as you can before your team is wiped out.
Badges measure how far you got. A run ends when every Pokemon has fainted.

HOW A TURN WORKS
- The map is a layered graph running top to bottom, with a boss at the bottom.
- You pick one node from the legal ones. The moment you pick, every other node on
  that layer CLOSES FOREVER. The choice is irreversible and it also decides which
  nodes you will be able to reach next.
- Battles resolve themselves. You never choose moves. What you decide is where to
  go, who to catch, which item to take and who to give it to.
- Your team holds up to 6 Pokemon.

NODE TYPES
  o catch        adds a Pokemon to your team
  x wild fight   one wild Pokemon, gives experience
  T trainer      1 Pokemon on map 0, 2 on maps 1-2, 3 from map 3 onwards
  i item         an item to equip or keep
  + pokecenter   restores HP
  ? unknown      only revealed when you enter it
  $ trade        M move tutor    S shop    B boss

WHAT ACTUALLY KILLS RUNS
Losing Pokemon. Every faint is permanent for that run, and once the team is empty
it is over, no matter how well you were doing.
"""

STRATEGIES = {
    # The plain one: the rules, and let the model work it out.
    "baseline": RULES + """
Think briefly, then call `play` with your chosen index. Always call `play`.""",

    # Bias towards not dying. Faints are what ends runs.
    "survivor": RULES + """
PLAY LIKE THIS
- Early on you have one Pokemon. If it faints you have lost. Widening the team is
  worth more than any experience you could gain.
- Never walk a Pokemon on low HP into a fight. Heal first if a pokecenter is
  reachable.
- Prefer a wild fight over a trainer when your team is thin: trainers bring more
  Pokemon and scale with the map.
- Type matchups decide battles. Check your team before choosing a fight.

Think briefly, then call `play`. Always call `play`.""",

    # Bias towards progression. Badges only come from moving forward.
    "explorer": RULES + """
PLAY LIKE THIS
- Badges are the only thing that counts, and they come from pushing down the map.
  Do not linger on safe nodes that add nothing.
- Before choosing, use `what_lies_ahead`: the node you take decides what is
  reachable next, and closing off a good branch costs more than one bad fight.
- A slightly risky fight that opens a good path beats a safe node that leads
  nowhere.
- Keep enough team to survive, but survival on its own scores nothing.

Think briefly, then call `play`. Always call `play`.""",

    # Force the model to look before it leaps.
    "analyst": RULES + """
HOW TO DECIDE
Before choosing, gather what you need:
1. Call `team_details` if any HP or type matchup could matter here.
2. Call `what_lies_ahead` whenever you are on the map. What a node leads to
   matters as much as the node itself, because the others close forever.
Only then call `play`, naming in one sentence the option you rejected and why.

Always finish with `play`.""",
}

DEFAULT_STRATEGY = "survivor"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "team_details",
            "description": "Full team stats: HP, levels, types, held items.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "what_lies_ahead",
            "description": (
                "For each legal action, which nodes it leads to on the next layer. "
                "Useful to avoid closing off good paths: this choice decides what "
                "you will be able to do next."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play",
            "description": "Perform the chosen action and end the turn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "index of the legal action"},
                    "why": {"type": "string", "description": "one sentence on the reason"},
                },
                "required": ["index", "why"],
            },
        },
    },
]


class LLMError(RuntimeError):
    pass


# ------------------------------------------------------------------------ bot


class LLMBot(Bot):
    name = "llm"

    def __init__(
        self,
        seed: int = 0,
        endpoint: str | None = None,
        token: str | None = None,
        model: str | None = None,
        max_rounds: int = 4,
        max_tokens: int = 1500,
        temperature: float = 0.6,
        memory: int = 6,
        strategy: str | None = None,
        verbose: bool = False,
    ) -> None:
        self.endpoint = (endpoint or os.environ.get("FW_ENDPOINT", "")).rstrip("/")
        self.token = token or os.environ.get("FW_TOKEN", "")
        self.model = model or os.environ.get("MODEL_ID", "")
        if not self.endpoint or not self.token:
            raise LLMError(
                "FW_ENDPOINT and FW_TOKEN environment variables are required\n"
                '  export FW_ENDPOINT="https://..."\n  export FW_TOKEN="..."'
            )
        if not self.model:
            raise LLMError('MODEL_ID is required, e.g. export MODEL_ID="gpt-4o-mini"')
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.memory = memory
        self.strategy = (
            strategy or os.environ.get("POKELIKE_LLM_STRATEGY") or DEFAULT_STRATEGY
        )
        if self.strategy not in STRATEGIES:
            raise LLMError(
                f"unknown strategy '{self.strategy}' — available: "
                f"{', '.join(sorted(STRATEGIES))}"
            )
        self.system = STRATEGIES[self.strategy]
        self.verbose = verbose or bool(os.environ.get("POKELIKE_VERBOSE"))

        # counters for the stats registry
        self.calls = 0
        self.tokens_used = 0
        self.fallbacks = 0
        self.journal: list[str] = []
        self._last_why = ""

    # ------------------------------------------------------------------ hooks

    def on_start(self, seed: int) -> None:
        self.journal = []
        self.calls = 0
        self.tokens_used = 0
        self.fallbacks = 0
        self._last_why = ""

    def notes(self) -> dict[str, Any]:
        """Ends up in the `extra` column of the run registry."""
        return {
            "model": self.model,
            "strategy": self.strategy,
            "calls": self.calls,
            "tokens": self.tokens_used,
            "fallbacks": self.fallbacks,
        }

    def artifacts(self) -> list:
        """What a submission of this bot carries.

        The prompt and the model reference, never the key. An LLM result cannot
        be reproduced exactly — providers change models behind a fixed name and
        sampling is stochastic — so the least we can do is record precisely what
        was asked of which model.
        """
        from ..leaderboard import Artifact

        return [
            Artifact(
                name="prompt.md",
                kind="prompt",
                description=f"system prompt, strategy '{self.strategy}'",
                text=self.system,
            ),
            Artifact(
                name="model.json",
                kind="model-ref",
                description="which model answered, and how it was asked",
                data={
                    "model": self.model,
                    "strategy": self.strategy,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "max_rounds": self.max_rounds,
                    "tools": [t["function"]["name"] for t in TOOLS],
                    "reproducible": False,
                    "why_not": (
                        "providers change models behind a fixed name and sampling is "
                        "stochastic; rerunning this will not give identical results"
                    ),
                },
            ),
        ]

    # --------------------------------------------------------------- decision

    def explain(self) -> str:
        return self._last_why

    def choose(self, state: dict[str, Any]) -> int:
        n = len(state["actions"])
        try:
            index, why = self._agentic_round(state)
        except Exception as e:  # noqa: BLE001 — no error may stop the run
            self.fallbacks += 1
            self._last_why = f"(fell back: {type(e).__name__})"
            if self.verbose:
                print(f"   [llm] fallback: {type(e).__name__}: {e}")
            return self._fallback(state)

        if not isinstance(index, int) or not 0 <= index < n:
            self.fallbacks += 1
            self._last_why = f"(fell back: model returned index {index})"
            if self.verbose:
                print(f"   [llm] invalid index ({index}), falling back")
            return self._fallback(state)

        self._last_why = why
        self.journal.append(f"step {state.get('steps')}: [{index}] {why[:90]}")
        self.journal = self.journal[-self.memory:]
        if self.verbose:
            print(f"   [llm] -> [{index}] {why[:100]}")
        return index

    def _fallback(self, state: dict[str, Any]) -> int:
        """Backup choice when the model does not answer or gets it wrong.

        Not random: it prefers what keeps the team alive — heal first if someone
        is hurt, otherwise widen the team.
        """
        actions = state["actions"]
        team = state.get("team") or []
        hurt = [p for p in team if p["max_hp"] and p["hp"] / p["max_hp"] < 0.4]

        order = ["pokecenter", "catch", "item"] if hurt else ["catch", "item", "pokecenter"]
        for kind in order:
            for i, a in enumerate(actions):
                if a.get("node") == kind:
                    return i
        return 0

    # ---------------------------------------------------------- agentic loop

    def _agentic_round(self, state: dict[str, Any]) -> tuple[int, str]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self._situation(state)},
        ]

        for _ in range(self.max_rounds):
            msg = self._call(messages)
            calls = msg.get("tool_calls") or []
            if not calls:
                # No tool: maybe it wrote the index out in prose.
                index = self._index_from_text(msg.get("content") or "", len(state["actions"]))
                if index is not None:
                    return index, "(read from prose)"
                raise LLMError("the model called no tool")

            messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": calls,
            })

            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}

                if name == "play":
                    return args.get("index"), str(args.get("why", ""))

                messages.append({
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": self._run_tool(name, state),
                })

        raise LLMError(f"no call to play() within {self.max_rounds} rounds")

    def _run_tool(self, name: str, state: dict[str, Any]) -> str:
        if name == "team_details":
            return render.team_view(state.get("team")) or "(empty team)"
        if name == "what_lies_ahead":
            return self._exits(state)
        return f"unknown tool: {name}"

    # ---------------------------------------------------------------- context

    def _situation(self, state: dict[str, Any]) -> str:
        parts = [render.screen(state)]
        if self.journal:
            parts += ["", "YOUR RECENT MOVES:", *(f"  {r}" for r in self.journal)]
        parts += [
            "",
            f"Pick an index between 0 and {len(state['actions']) - 1} and call play().",
        ]
        return "\n".join(parts)

    def _exits(self, state: dict[str, Any]) -> str:
        """Where each legal action leads, by reading the map's edges."""
        m = state.get("map")
        if not m:
            return "You are not on the map: this choice opens or closes no paths."
        by_id = {n["id"]: n for n in m["nodes"]}
        rows = []
        for i, a in enumerate(state["actions"]):
            if a.get("kind") != "node":
                rows.append(f"  [{i}] {a.get('label', '')[:60]}")
                continue
            after = [by_id[t]["kind"] for f, t in m["edges"] if f == a["id"] and t in by_id]
            follows = ", ".join(sorted(after)) if after else "nothing (end of map)"
            rows.append(f"  [{i}] {a['node']:<12} -> leads to: {follows}")
        return "Exits on the next layer:\n" + "\n".join(rows)

    # ------------------------------------------------------------------- HTTP

    def _call(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.endpoint}/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                answer = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise LLMError(f"HTTP {e.code}: {e.read()[:200]!r}") from e
        except Exception as e:  # network, timeout, malformed JSON
            raise LLMError(f"{type(e).__name__}: {e}") from e

        self.calls += 1
        self.tokens_used += (answer.get("usage") or {}).get("total_tokens", 0)
        choices = answer.get("choices") or []
        if not choices:
            raise LLMError("response had no choices")
        return choices[0].get("message") or {}

    @staticmethod
    def _index_from_text(text: str, n: int) -> int | None:
        """Last resort: fish a valid index out of a prose answer."""
        import re

        for m in re.finditer(r"\[?(\d+)\]?", text):
            v = int(m.group(1))
            if 0 <= v < n:
                return v
        return None
