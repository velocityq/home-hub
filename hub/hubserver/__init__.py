"""The real home hub (part A). Run: cd hub && .venv/bin/python -m hubserver [--port N]."""
import os
import sys

# contract.py lives one folder up (hub/), and so does the ask/ package.
HUB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HUB_DIR not in sys.path:
    sys.path.insert(0, HUB_DIR)

__all__ = ["HUB_DIR"]
