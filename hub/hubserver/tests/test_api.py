"""The hub's routes, keys, CORS, pairing, events socket, Ask mount and wall serving (fake devices)."""
import asyncio
import json
import os
import stat

from hubserver import config as cfgmod

from .conftest import MCP_KEY, WALL_KEY, auth, build, close, is_private, wait_for


async def test_health_needs_no_key(hub):
    r = await hub.client.get("/api/health")
    assert r.status == 200
    assert await r.json() == {"ok": True, "version": 1}


async def test_no_key_wrong_key(hub):
    for path in ("/api/state", "/api/actions"):
        r = await hub.client.get(path)
        assert r.status == 401
        assert await r.json() == {"ok": False, "error": "This needs the hub key."}
        r = await hub.client.get(path, headers=auth("nope-nope-nope-nope-nope"))
        assert r.status == 401
        r = await hub.client.get(path, headers={"Authorization": WALL_KEY})   # no "Bearer "
        assert r.status == 401
    r = await hub.client.post("/api/action", json={"action": "aircon.power", "args": {"on": True}})
    assert r.status == 401
    r = await hub.client.post("/api/ask", json={"text": "hi"})
    assert r.status == 401
    r = await hub.client.post("/api/ask/audio", data=b"x", headers={"Content-Type": "audio/wav"})
    assert r.status == 401


async def test_both_keys_work(hub):
    for k in (WALL_KEY, MCP_KEY):
        r = await hub.client.get("/api/state", headers=auth(k))
        assert r.status == 200


async def test_state_shape(hub):
    r = await hub.client.get("/api/state", headers=auth())
    body = await r.json()
    st = body["state"]
    assert st["version"] == 1
    ac = st["aircon"]
    assert ac["available"] is True and ac["power"] is True and ac["mode"] == "cool" and ac["set"] == 22
    assert ac["fan_speeds"] == ["auto", "low", "medium", "high"]
    assert [z["id"] for z in ac["zones"]] == ["living", "media", "rumpus", "master-bed", "bed-2", "bed-3", "bed-4"]
    assert ac["inside"] == 23.6
    assert all(z["name"] != "Zone8" for z in ac["zones"])
    sp = st["speakers"]
    assert [d["id"] for d in sp["devices"]] == ["lounge-room", "theatre", "outside"]
    assert sp["groups"] == [{"id": "lounge-room+outside", "name": "Lounge + Outside",
                             "members": ["lounge-room", "outside"]}]
    assert sp["now"]["source"] == "cast" and sp["now"]["on"] == ["lounge-room", "outside"]
    assert sp["spotify"] == {"linked": False}
    tv = st["tvs"]
    assert [d["id"] for d in tv["devices"]] == ["living-room", "bedroom", "frame"]
    assert [d["name"] for d in tv["devices"]] == ["Living Room", "Bedroom", "The Frame"]
    assert tv["devices"][0]["app"] == "YouTube" and tv["devices"][0]["volume"] == 18
    assert tv["devices"][2]["art_mode"] is True
    assert tv["apps"] == ["YouTube", "Netflix", "ABC iview"]


async def test_actions_list(hub):
    r = await hub.client.get("/api/actions", headers=auth())
    names = [a["action"] for a in (await r.json())["actions"]]
    assert "aircon.zone" in names and "tv.art_mode" in names


async def test_bad_requests(hub):
    c = hub.client
    r = await c.post("/api/action", data="not json", headers={**auth(), "Content-Type": "application/json"})
    assert r.status == 400 and (await r.json())["error"] == "The request was not valid JSON."
    r = await c.post("/api/action", json=[1, 2], headers=auth())
    assert r.status == 400
    r = await c.post("/api/action", json={"action": "shell.run", "args": {}}, headers=auth())
    assert r.status == 400 and (await r.json())["error"] == "That is not something the hub can do."
    r = await c.post("/api/action", json={"action": "aircon.set_temp", "args": {"value": 40}}, headers=auth())
    assert r.status == 400 and "between 16 and 30" in (await r.json())["error"]
    r = await c.post("/api/action", json={"action": "aircon.zone", "args": {"zone": "living"}}, headers=auth())
    assert r.status == 400 and "Missing argument" in (await r.json())["error"]
    r = await c.post("/api/action", json={"action": "aircon.zone", "args": {"zone": "garage", "on": True}},
                     headers=auth())
    assert r.status == 400


async def test_options_and_cors(home):
    c = await build(home, cors=("http://192.0.2.10:8790",))
    try:
        r = await c.client.options("/api/state", headers={"Origin": "http://192.0.2.10:8790"})
        assert r.status == 204
        assert r.headers["Access-Control-Allow-Origin"] == "http://192.0.2.10:8790"
        assert "Authorization" in r.headers["Access-Control-Allow-Headers"]
        r = await c.client.options("/api/state", headers={"Origin": "http://evil.example"})
        assert r.status == 204 and "Access-Control-Allow-Origin" not in r.headers
        r = await c.client.get("/api/state", headers={"Origin": "http://evil.example", **auth()})
        assert r.status == 200 and "Access-Control-Allow-Origin" not in r.headers
        r = await c.client.get("/api/state", headers={"Origin": "http://192.0.2.10:8790", **auth()})
        assert r.headers["Access-Control-Allow-Origin"] == "http://192.0.2.10:8790"
        r = await c.client.get("/api/state", headers={"Origin": "http://192.0.2.10:8790"})
        assert r.status == 401 and r.headers["Access-Control-Allow-Origin"] == "http://192.0.2.10:8790"
        assert r.headers.get("Access-Control-Allow-Origin") != "*"
    finally:
        await close(c)


async def test_star_origin_is_ignored(home):
    cfgmod.write_json(cfgmod.path("config.json"), {"cors_origins": ["*", "http://ok.example"]}, mode=0o644)
    cfg = cfgmod.load_config()
    assert cfg["cors_origins"] == ["http://ok.example"]


async def test_keys_file_made_with_mode_600(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "h"))
    monkeypatch.delenv("HUB_KEYS_FILE", raising=False)
    k = cfgmod.Keys()
    p = tmp_path / "h" / "keys.json"
    assert is_private(p, 0o600)
    assert is_private(tmp_path / "h", 0o700)
    data = json.loads(p.read_text())
    assert sorted(data["clients"]) == ["couch-tv", "mcp", "wall"]
    assert len({*data["clients"].values()}) == 3
    assert k.who(data["clients"]["wall"]) == "wall"
    assert k.who("x" * 43) is None and k.who("") is None and k.who(None) is None


async def test_pairing(hub, monkeypatch):
    import hubserver.app as appmod
    sleeps = []
    real_sleep = asyncio.sleep

    async def fast_sleep(t, *a, **kw):
        sleeps.append(t)
        await real_sleep(0)
    monkeypatch.setattr(appmod.asyncio, "sleep", fast_sleep)
    c = hub.client
    r = await c.post("/api/pair", json={"code": "000000", "name": "phone"})
    assert r.status == 403
    code = cfgmod.new_pair_code()
    wrong = "%06d" % ((int(code) + 1) % 1000000)
    r = await c.post("/api/pair", json={"code": wrong, "name": "phone"})
    assert r.status == 403 and sleeps and sleeps[-1] > 0
    r = await c.post("/api/pair", json={"code": code, "name": "Phone Sam"})
    assert r.status == 200
    body = await r.json()
    assert body["ok"] and body["name"] == "phone-sam" and len(body["key"]) > 30
    r = await c.get("/api/state", headers=auth(body["key"]))
    assert r.status == 200
    # the code works once
    r = await c.post("/api/pair", json={"code": code, "name": "again"})
    assert r.status == 403


async def test_pairing_five_tries_per_code(hub, monkeypatch):
    import hubserver.app as appmod
    real_sleep = asyncio.sleep

    async def fast_sleep(t, *a, **kw):
        await real_sleep(0)
    monkeypatch.setattr(appmod.asyncio, "sleep", fast_sleep)
    code = cfgmod.new_pair_code()
    wrong = "%06d" % ((int(code) + 1) % 1000000)
    for _ in range(5):
        r = await hub.client.post("/api/pair", json={"code": wrong})
        assert r.status == 403
    r = await hub.client.post("/api/pair", json={"code": code})
    assert r.status == 403   # the code is gone after 5 wrong tries


async def test_pair_cli_prints_code(home, capsys):
    from hubserver.__main__ import main
    main(["pair"])
    out = capsys.readouterr().out
    import re
    code = re.search(r"Pairing code: (\d{6})", out).group(1)
    assert cfgmod.check_pair_code(code)
    assert is_private(home / "keys.json", 0o600) or is_private(home / "keys.json", 0o644)  # (test file)


async def test_events_socket(hub):
    c = hub.client
    r = await c.get("/api/events")
    assert r.status == 401
    r = await c.get("/api/events?key=wrong")
    assert r.status == 401
    ws = await c.ws_connect(f"/api/events?key={WALL_KEY}")
    first = await ws.receive_json(timeout=3)
    assert first["type"] == "state" and first["state"]["version"] == 1
    await ws.send_json({"type": "ping"})
    assert (await ws.receive_json(timeout=3)) == {"type": "pong"}
    r = await c.post("/api/action", json={"action": "aircon.set_temp", "args": {"value": 24}}, headers=auth())
    assert r.status == 200
    msg = await ws.receive_json(timeout=3)
    assert msg["type"] == "state" and msg["state"]["aircon"]["set"] == 24
    await ws.close()


async def test_events_throttled(hub):
    ws = await hub.client.ws_connect(f"/api/events?key={WALL_KEY}")
    await ws.receive_json(timeout=3)
    for v in (23, 24, 25, 26):
        await hub.client.post("/api/action", json={"action": "aircon.set_temp", "args": {"value": v}}, headers=auth())
    got = []
    try:
        while True:
            got.append(await ws.receive_json(timeout=0.8))
    except asyncio.TimeoutError:
        pass
    assert got and got[-1]["state"]["aircon"]["set"] == 26
    assert len(got) <= 5
    await ws.close()


async def test_ask_not_ready(hub, monkeypatch):
    import builtins
    real = builtins.__import__

    def no_ask(name, *a, **kw):
        if name == "ask":
            raise ImportError("no ask")
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_ask)
    r = await hub.client.post("/api/ask", json={"text": "warmer", "source": "wall"}, headers=auth())
    assert r.status == 503 and (await r.json())["error"] == "Ask is not ready yet."
    r = await hub.client.post("/api/ask", json={"text": ""}, headers=auth())
    assert r.status == 400


class FakeAsk:
    def __init__(self, get_state, run_action, config):
        self.get_state, self.run_action, self.config = get_state, run_action, config

    async def ask_text(self, text, source):
        st = await self.get_state()
        res = await self.run_action("aircon.nudge", {"delta": 1})
        bad = await self.run_action("shell.run", {})
        return {"heard": text, "reply": f"Set to {st['aircon']['set'] + 1}", "via": "fast",
                "actions": [{"action": "aircon.nudge", "args": {"delta": 1}, **res}, {"action": "shell.run", **bad}]}

    async def ask_audio(self, data, mime, source):
        return {"heard": f"{len(data)} {mime}", "reply": "ok", "actions": [], "via": "none"}


async def test_ask_mounted(home):
    c = await build(home, ask_factory=FakeAsk)
    try:
        r = await c.client.post("/api/ask", json={"text": "warmer", "source": "wall"}, headers=auth())
        body = await r.json()
        assert r.status == 200 and body["ok"] and body["reply"] == "Set to 23"
        assert body["actions"][0]["ok"] is True
        assert body["actions"][1]["ok"] is False and "not something" in body["actions"][1]["error"]
        assert c.hub.state()["aircon"]["set"] == 23
        r = await c.client.post("/api/ask/audio?source=wall", data=b"abc", headers={"Content-Type": "audio/webm",
                                                                                    **auth()})
        assert (await r.json())["heard"] == "3 audio/webm"
        r = await c.client.post("/api/ask/audio", data=b"", headers={"Content-Type": "audio/webm", **auth()})
        assert (await r.json())["reply"] == "I didn't catch that."
        r = await c.client.post("/api/ask/audio", data=b"x" * (2 * 1024 * 1024 + 10),
                                headers={"Content-Type": "audio/webm", **auth()})
        assert r.status == 400 and "2 MB" in (await r.json())["error"]
        r = await c.client.post("/api/ask/audio", data=b"abc", headers={"Content-Type": "text/plain", **auth()})
        assert r.status == 400
    finally:
        await close(c)


async def test_wall_missing_and_present(home):
    c = await build(home)
    try:
        r = await c.client.get("/")
        assert r.status == 503 and "not installed" in await r.text()
    finally:
        await close(c)
    wall = home / "wall"
    (wall / "js").mkdir(parents=True)
    (wall / "index.html").write_text("<h1>wall</h1>")
    (wall / "js" / "app.js").write_text("console.log(1)")
    (home / "secret.txt").write_text("no")
    c = await build(home, wall_dir=str(wall))
    try:
        r = await c.client.get("/")
        assert r.status == 200 and "wall" in await r.text()
        r = await c.client.get("/js/app.js")
        assert r.status == 200
        r = await c.client.get("/wall/js/app.js")
        assert r.status == 200
        r = await c.client.get("/../secret.txt")
        assert r.status == 404
        r = await c.client.get("/%2e%2e/secret.txt")
        assert r.status == 404
    finally:
        await close(c)


async def test_spotify_login_only_local(hub):
    # The test client connects from 127.0.0.1, so make the request look remote.
    from unittest import mock
    with mock.patch("aiohttp.web_request.BaseRequest.remote", new_callable=mock.PropertyMock,
                    return_value="192.0.2.50"):
        r = await hub.client.get("/spotify/login", allow_redirects=False)
        assert r.status == 403
    r = await hub.client.get("/spotify/login", allow_redirects=False)
    assert r.status == 409 and "client id" in (await r.text()).lower()


async def test_unknown_api_path(hub):
    r = await hub.client.get("/api/nothing", headers=auth())
    assert r.status == 404 and (await r.json())["ok"] is False


async def test_action_log_has_name_not_key(hub, caplog):
    import logging
    caplog.set_level(logging.INFO)
    await hub.client.post("/api/action", json={"action": "aircon.set_temp", "args": {"value": 21}},
                          headers=auth(MCP_KEY))
    text = caplog.text
    assert "by mcp" in text and MCP_KEY not in text and WALL_KEY not in text


async def test_secret_filter():
    import logging
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "GET /api/events?key=%s now", ("abcdefghijklmnop",), None)
    cfgmod._NoSecrets().filter(rec)
    assert "abcdefghijklmnop" not in rec.getMessage()


async def test_state_after_device_change_pushes(hub):
    ws = await hub.client.ws_connect(f"/api/events?key={WALL_KEY}")
    await ws.receive_json(timeout=3)
    hub.cast.set_volume(hub.cast.speakers["theatre"]["uuid"], 77)   # someone used the Google Home app
    msg = await ws.receive_json(timeout=3)
    assert next(d for d in msg["state"]["speakers"]["devices"] if d["id"] == "theatre")["volume"] == 77
    await ws.close()
    assert await wait_for(lambda: not hub.hub.sockets)
