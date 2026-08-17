"""The game stated as an MDP: states, actions, rewards, and the env adapter.

This is what a Reinforcement Learning method needs and nothing else does. The
LLM experiment reads the raw observation and imports none of it, which is
exactly why this is not called `common`: it never was.

    encoding.py     observation -> hashable state key, action -> stable key
    rewards.py      five reward functions, selectable by name
    environment.py  TrainingEnv: reset/step in those terms
"""

from . import rewards
from .encoding import ENCODING_VERSION, action_key, state_key
from .environment import TrainingEnv

__all__ = ["TrainingEnv", "state_key", "action_key", "rewards", "ENCODING_VERSION"]
