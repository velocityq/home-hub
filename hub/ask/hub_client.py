"""get_state / run_action over HTTP against a hub (real or fake), for tests and manual use.

    client = HubClient("http://127.0.0.1:8797", "testkey")
    engine = AskEngine(client.get_state, client.run_action, {})
    ...
    await client.close()

Or from the shell:
    hub/.venv/bin/python -m ask.hub_client --hub http://127.0.0.1:8797 --key testkey "make it warmer"
    hub/.venv/bin/python -m ask.hub_client --hub ... --key ... --audio clip.webm
(run from the hub/ folder)
"""
from __future__ import annotations

import aiohttp


class HubClient:
    def __init__(self, base_url, key, timeout=15):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {key}"}
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = None

    async def _s(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers, timeout=self.timeout)
        return self._session

    async def get_state(self):
        s = await self._s()
        async with s.get(f"{self.base}/api/state") as r:
            body = await r.json(content_type=None)
            if r.status != 200 or not body.get("ok"):
                raise RuntimeError(body.get("error") or f"hub answered {r.status}")
            return body["state"]

    async def run_action(self, action, args):
        s = await self._s()
        try:
            async with s.post(f"{self.base}/api/action", json={"action": action, "args": args}) as r:
                body = await r.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as e:
            return {"ok": False, "error": f"The hub did not answer ({type(e).__name__})."}
        if isinstance(body, dict) and body.get("ok"):
            return {"ok": True}
        return {"ok": False, "error": (body or {}).get("error") or "That did not work."}

    async def close(self):
        if self._session is not None:
            await self._session.close()


async def _main():
    import argparse
    import json
    import mimetypes

    from ask import AskEngine

    ap = argparse.ArgumentParser(description="Ask the house something, through a hub.")
    ap.add_argument("--hub", default="http://127.0.0.1:8797")
    ap.add_argument("--key", required=True)
    ap.add_argument("--audio", help="a recording to send instead of text")
    ap.add_argument("text", nargs="*")
    a = ap.parse_args()
    client = HubClient(a.hub, a.key)
    engine = AskEngine(client.get_state, client.run_action, {})
    try:
        if a.audio:
            with open(a.audio, "rb") as f:
                data = f.read()
            ans = await engine.ask_audio(data, mimetypes.guess_type(a.audio)[0] or "", "cli")
        else:
            ans = await engine.ask_text(" ".join(a.text), "cli")
        print(json.dumps(ans, indent=2))
        print("timing:", engine.last_timing)
    finally:
        await client.close()


if __name__ == "__main__":
    import asyncio
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    asyncio.run(_main())
