"""How something outside drives the game.

Two entry points, both thin faces over `core.game.Game`:

    cli/    a human, in a terminal
    api/    a program, over HTTP

`bot/` deliberately lives elsewhere. It is not an entry point but an extension
point: you write a bot, and these interfaces run it. Putting implementations
(random, llm, dyna_q) under `interfaces/` would blur that distinction.
"""
