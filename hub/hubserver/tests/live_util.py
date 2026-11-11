"""Helpers for the live tests: they talk to a running hub over HTTP, never to port 8790 while building."""
import json
import os
import time
from urllib.parse import urlparse

import aiohttp

URL = os.environ.get("HUB_LIVE_URL", "http://127.0.0.1:8791").rstrip("/")
RECORD = os.path.expanduser(os.environ.get("HUB_LIVE_RECORD", "~/.home-hub/logs/live-tests.jsonl"))


def key():
    p = os.path.expanduser(os.environ.get("HUB_KEYS_FILE") or "~/.home-hub/keys.json")
    with open(p) as f:
        clients = json.load(f)["clients"]
    return clients.get("mcp") or next(iter(clients.values()))


def check_port():
    port = urlparse(URL).port
    assert port != 8790 or os.environ.get("HUB_LIVE_ALLOW_8790") == "1", \
        "live tests run against the build hub on 8791, not 8790"


class Live:
    def __init__(self):
        check_port()
        self.h = {"Authorization": f"Bearer {key()}"}
        self.s = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=70))

    async def close(self):
        await self.s.close()

    async def state(self):
        async with self.s.get(URL + "/api/state", headers=self.h) as r:
            assert r.status == 200
            return (await r.json())["state"]

    async def act(self, action, args=None):
        async with self.s.post(URL + "/api/action", json={"action": action, "args": args or {}}, headers=self.h) as r:
            body = await r.json()
            return r.status, body


def record(test, before, after, **extra):
    """Keep every live change on file: what it was, what it became, what it went back to."""
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "test": test, "before": before, "after": after, **extra}
    os.makedirs(os.path.dirname(RECORD), exist_ok=True)
    with open(RECORD, "a") as f:
        f.write(json.dumps(row) + "\n")
    print(f"\nLIVE {test}: {json.dumps({k: v for k, v in row.items() if k != 'at'})}")


def zone(st, zid):
    return next(z for z in st["aircon"]["zones"] if z["id"] == zid)


def device(st, part, did):
    return next(d for d in st[part]["devices"] if d["id"] == did)
