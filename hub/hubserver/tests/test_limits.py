"""Ask is capped per client, and a revoked key stops working at once."""
import json
import os

import pytest

from hubserver import app as appmod
from hubserver import config as cfgmod


def test_revoke_removes_a_client(tmp_path, monkeypatch):
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"clients": {"wall": "w" * 32, "phone-sam": "p" * 32}}))
    os.chmod(p, 0o600)
    keys = cfgmod.Keys(str(p))
    assert keys.who("p" * 32) == "phone-sam"
    assert keys.revoke("phone-sam") is True
    assert keys.who("p" * 32) is None
    assert keys.who("w" * 32) == "wall"
    assert keys.revoke("nobody") is False


def test_ask_limit_constants():
    assert appmod.ASK_LIMIT == 30 and appmod.ASK_WINDOW == 600
