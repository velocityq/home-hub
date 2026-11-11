"""Start the stdio MCP server.

Works both as `python -m homemcp` from hub/ and as `python /path/to/hub/homemcp` from anywhere.
"""
import os
import sys

if __package__ in (None, ""):
    # Run as a folder: put hub/ on the path (not this folder, so nothing here shadows a library).
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
    sys.path.insert(0, os.path.dirname(here))

from homemcp.server import main  # noqa: E402

main()
