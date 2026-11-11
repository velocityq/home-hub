"""The Ask module (part C): voice and text questions to house actions.

    from ask import AskEngine
    engine = AskEngine(get_state, run_action, config)

See README.md for the config keys.
"""
import os
import sys

_HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HUB not in sys.path:            # contract.py lives in hub/
    sys.path.insert(0, _HUB)

from .engine import DEFAULTS, AskEngine  # noqa: E402

__all__ = ["AskEngine", "DEFAULTS"]
