"""llm-example: every knob the harness has, turned, with a reason for each.

    export FW_ENDPOINT="https://..."   # base URL, no /v1
    export FW_TOKEN="..."
    export MODEL_ID="..."
    uv run pokelike bot --bot llm-example --runs 1 -d

**This is a reference, not a contender.** The other `llm-*` bots each change one
thing so the comparison between them means something; this one changes
everything at once, which is the right way to show the surface and the wrong way
to learn anything from a score. Copy the parts you want.

What it demonstrates, in the order it appears below:

    PROMPT          the system prompt -- for most bots, the whole submission
    MODEL           pinning a model id, and why you might not
    TEMPERATURE     sampling
    MAX_TOKENS      ceiling on one answer
    MAX_ROUNDS      tool rounds before the turn is given up on
    MEMORY          how many past turns are shown back to the model
    TOKEN_BUDGET    a per-run ceiling that stops the run instead of surprising you
    EXTRA_TOOLS     tools of your own, on top of the shared four
    run_tool()      answering them
    tools()         the whole set, if you would rather rebuild it
    STATE_VIEW      what the model reads: "screen" | "json" | "both" | [keys]
    view()          the same thing, when none of those four fit
    _fallback()     what to play when the model does not answer
    explain()       one line per decision in the log
    notes()         what gets recorded next to your score

`_call()` is the one hook not used here. Override it to put something other than
an HTTP endpoint behind the harness -- a local transformers model, a llama.cpp
process, a fake that replays a transcript in a test. Return the OpenAI-shaped
`message` dict and everything above keeps working.
"""

from __future__ import annotations

import json
from typing import Any

from pokelike.bot.llm import GAME_RULES, LLMBot
from pokelike.core import render


class ExampleBot(LLMBot):
    name = "llm-example"

    # ------------------------------------------------------------------ prompt
    #
    # GAME_RULES is the factual half, read out of the game bundle rather than
    # guessed -- trainer counts per map, what closes when you pick a node. Keep
    # it and add strategy, or drop it entirely if you think the facts are what
    # is holding the model back. That is a legitimate experiment; it is just a
    # different one.

    PROMPT = GAME_RULES + """
PLAY LIKE THIS
- Read `state_json` when the summary is not enough. It is the same dict the
  Python bots see, so nothing is being kept from you.
- Ask `bag` before spending a turn on an item node: carrying a second potion is
  worth less than almost anything else you could do with the turn.
- Weigh `set_lead` on every map turn. It is free -- it does not consume the turn
  -- and who enters the battle first decides most battles.

Think briefly, then call `play`. Always call `play`."""

    # ------------------------------------------------------- the model, and how
    #
    # MODEL = None takes $MODEL_ID, which is what you want while experimenting
    # and what the four prompt bots do. Pin a string here instead and the id
    # goes into the fingerprint, so the row means one specific model for good
    # and swapping it shows up as a changed bot. The id is not a secret; the
    # endpoint and the token are, and they only ever come from the environment.
    MODEL = None

    # Low, not zero. Zero is not reproducible either -- providers do not promise
    # it -- and it makes a stuck model stay stuck for a whole run.
    TEMPERATURE = 0.3

    # Enough for a short reason plus a tool call. Raise it if your prompt asks
    # the model to think out loud; every token here is paid fifty times over a
    # benchmark.
    MAX_TOKENS = 900

    # Tool rounds before the turn is abandoned to the fallback. This bot offers
    # two extra tools and its prompt tells the model to use them, so four rounds
    # would be tight: state_json, bag, then play is already three.
    MAX_ROUNDS = 6

    # Past turns replayed to the model. Long enough to notice it is going in
    # circles, short enough not to pay for the whole run every turn.
    MEMORY = 8

    # A per-run ceiling. One run is roughly 30k tokens; this stops a pathological
    # run at about double that instead of letting fifty of them surprise you on
    # the bill. Hitting it raises LLMBudgetError and ENDS the run -- deliberately
    # not a fallback, because a run that spent its budget is not a run the model
    # played badly, it is a run that did not finish.
    TOKEN_BUDGET = 60_000

    # -------------------------------------------------------------- extra tools
    #
    # Declared here, answered in `run_tool`. Nothing stops you giving the model
    # something the shared four do not offer -- but your result records that
    # your tool set differs, and the standings mark the row. Not as a fault:
    # you are answering a different question, and the mistake would be comparing
    # it with the rest as though it were the same one.

    EXTRA_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "state_json",
                "description": (
                    "The raw state dict, as JSON: team, bag, map, run, actions. "
                    "Everything the Python bots see. Use it when the summary "
                    "leaves out something you need."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "part": {
                            "type": "string",
                            "description": (
                                "which key to return, or 'all'. One key is far "
                                "cheaper than the whole thing."
                            ),
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "bag",
                "description": "What you are carrying, by name.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    def run_tool(self, name: str, args: dict[str, Any], state: dict[str, Any]) -> str:
        """Answers a tool call. Whatever this returns is what the model reads.

        Two rules worth keeping. Never raise: an exception here throws the turn
        away and hands it to the fallback, so a model that mistypes a tool name
        costs you a decision. And always end with `super()`, or you silently
        take away the shared tools while still claiming to offer them.
        """
        if name == "bag":
            return ", ".join(state.get("bag") or []) or "(carrying nothing)"

        if name == "state_json":
            part = (args or {}).get("part") or "all"
            payload = state if part == "all" else {part: state.get(part)}
            if part != "all" and state.get(part) is None:
                return (f"no key '{part}' in the state. Available: "
                        f"{', '.join(sorted(state))}")
            # Truncated on purpose: the map of a late run is large, and a tool
            # reply that fills the context window costs the model the reasoning
            # it was about to do.
            text = json.dumps(payload, separators=(",", ":"))
            return text if len(text) <= 4000 else text[:4000] + " ...(truncated)"

        return super().run_tool(name, args, state)

    def tools(self) -> list[dict[str, Any]]:
        """The full set offered to the model.

        The default is `[*TOOLS, *EXTRA_TOOLS]` and that is what this does, so
        overriding it here buys nothing -- it is spelled out only to show where
        you would intervene to REMOVE a shared tool. `play` has to survive: it
        is how a turn ends, and a set without it is refused at construction
        rather than discovered fifty runs in, when every turn has fallen back.
        """
        return super().tools()

    # ----------------------------------------------- how the state reaches it
    #
    # The deepest hook in the harness, and the one worth thinking hardest about.
    # Everything else changes what the model is told to do; this changes what it
    # is told. The default renders the ASCII screen a human sees plus a journal
    # of recent moves.

    STATE_VIEW = "screen"

    def view(self, state: dict[str, Any]) -> str:
        """The rendered screen, plus a compact numeric line the screen omits.

        The point of the extra line: the ASCII view is built for a person, so it
        shows HP as a bar and the map as a picture. A model reading '19/19' has
        to do arithmetic to compare two teams, and arithmetic is where it will
        make the mistake. Handing it the fractions directly costs about twenty
        tokens.

        The full dict is NOT pushed here on purpose -- it is a tool instead. A
        map late in a run is several kilobytes, most of it irrelevant to this
        turn, and paying for it on every single turn is how an LLM benchmark
        becomes about context windows rather than about play. `bots/llm-raw/`
        takes the other side of that bet with the same prompt, which is what
        makes the pair worth measuring.

        Note what this canNOT break: the journal and the "pick an index" line are
        added by the harness around whatever comes back from here, so replacing
        the view outright never costs the bot its memory.
        """
        base = render.screen(state)
        team = state.get("team") or []
        if not team:
            return base

        hp = " ".join(
            f"{p['name']}:{p['hp'] / p['max_hp']:.0%}" if p.get("max_hp") else f"{p['name']}:?"
            for p in team
        )
        lead = team[0]["name"]
        return (f"{base}\n\nTEAM HP: {hp}\n"
                f"LEADING THE NEXT BATTLE: {lead} (slot 0)\n"
                f"Call state_json if you need anything not shown above.")

    # --------------------------------------------------------------- fallback
    #
    # Used when a call times out, comes back unusable, or never reaches `play`.
    # Overriding it is allowed and rarely wise: whatever it does is played under
    # your bot's name, and the standings report the share of turns it decided.

    def _fallback(self, state: dict[str, Any]) -> int:
        """Heal, else catch, else the first legal move.

        Same shape as the harness default, kept here so the file shows where the
        hook is. If yours is cleverer than the shared one, that cleverness is
        being measured as though the model produced it -- which is the argument
        for leaving it alone.
        """
        actions = state["actions"]
        team = state.get("team") or []
        hurt = any(p["hp"] / p["max_hp"] < 0.4 for p in team if p.get("max_hp"))
        for want in (("pokecenter",) if hurt else ()) + ("catch", "pokecenter"):
            for i, a in enumerate(actions):
                if a.get("node") == want:
                    return i
        return 0

    # ------------------------------------------------------------- reporting

    def explain(self) -> str:
        """One line under each decision in `-d` logs.

        The harness fills `_last_why` with the model's own stated reason, or
        with why the turn fell back. Prefixed here so a log makes it obvious at
        a glance which bot was talking.
        """
        return f"[example] {super().explain()}"

    def notes(self) -> dict[str, Any]:
        """Recorded in the run registry and in `result.json`.

        Never put the token or the endpoint in here. `stats/` is gitignored and
        `result.json` is not, and a result file is exactly the kind of thing
        that gets pasted into an issue.
        """
        return {**super().notes(), "extra_tools": [t["function"]["name"]
                                                   for t in self.EXTRA_TOOLS]}
