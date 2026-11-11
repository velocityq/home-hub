"""The contract suite: the same requests go to hub/fake_hub.py and to the real hub (with fake devices).
Status codes, error words and the shape of the state must match. Every known difference is listed
in KNOWN_DIFFS with its reason, and checked to be exactly that difference.
"""
import json
import os
import sys

import pytest
from aiohttp.test_utils import TestClient, TestServer

from .conftest import WALL_KEY, auth, build, close
from .fakes import FakeAirtouch
from .test_api import FakeAsk

HUB_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HUB_DIR)
import fake_hub  # noqa: E402

ORIGIN = "http://192.0.2.10:8790"

# (method, path, json body or raw bytes, headers kind)
REQUESTS = [
    ("GET", "/api/health", None, "none"),
    ("GET", "/api/state", None, "none"),
    ("GET", "/api/state", None, "wrong"),
    ("GET", "/api/state", None, "key"),
    ("GET", "/api/actions", None, "none"),
    ("GET", "/api/actions", None, "key"),
    ("POST", "/api/action", b"{not json", "key"),
    ("POST", "/api/action", [1, 2], "key"),
    ("POST", "/api/action", {"action": "rm -rf", "args": {}}, "key"),
    ("POST", "/api/action", {"action": "aircon.zone", "args": {"zone": "living"}}, "key"),
    ("POST", "/api/action", {"action": "aircon.zone", "args": {"zone": "garage", "on": True}}, "key"),
    ("POST", "/api/action", {"action": "aircon.set_temp", "args": {"value": 31}}, "key"),
    ("POST", "/api/action", {"action": "aircon.set_temp", "args": {"value": 22.5}}, "key"),
    ("POST", "/api/action", {"action": "aircon.power", "args": {"on": "yes"}}, "key"),
    ("POST", "/api/action", {"action": "aircon.power", "args": {"on": True, "extra": 1}}, "key"),
    ("POST", "/api/action", {"action": "aircon.power", "args": "on"}, "key"),
    ("POST", "/api/action", {"action": "speakers.volume", "args": {"speaker": "kitchen", "value": 5}}, "key"),
    ("POST", "/api/action", {"action": "music.speakers", "args": {"speakers": []}}, "key"),
    ("POST", "/api/action", {"action": "tv.art_mode", "args": {"tv": "bedroom", "on": True}}, "key"),
    ("POST", "/api/action", {"action": "music.search_play", "args": {"query": ""}}, "key"),
    ("POST", "/api/action", {"action": "aircon.power", "args": {"on": True}}, "none"),
    ("POST", "/api/action", {"action": "aircon.power", "args": {"on": True}}, "key"),
    ("POST", "/api/action", {"action": "aircon.set_temp", "args": {"value": 24}}, "key"),
    ("POST", "/api/action", {"action": "aircon.nudge", "args": {"delta": -1}}, "key"),
    ("POST", "/api/action", {"action": "aircon.mode", "args": {"mode": "heat"}}, "key"),
    ("POST", "/api/action", {"action": "aircon.fan", "args": {"speed": "turbo"}}, "key"),
    ("POST", "/api/action", {"action": "aircon.zone", "args": {"zone": "living", "on": True}}, "key"),
    ("POST", "/api/action", {"action": "aircon.zones_all", "args": {"on": False}}, "key"),
    ("POST", "/api/action", {"action": "speakers.volume", "args": {"speaker": "theatre", "value": 20}}, "key"),
    ("POST", "/api/action", {"action": "speakers.volume", "args": {"speaker": "all", "value": 25}}, "key"),
    ("POST", "/api/action", {"action": "music.pause"}, "key"),
    ("POST", "/api/action", {"action": "music.play", "args": {}}, "key"),
    ("POST", "/api/action", {"action": "music.next", "args": {}}, "key"),
    ("POST", "/api/action", {"action": "music.previous", "args": {}}, "key"),
    ("POST", "/api/action", {"action": "music.speakers", "args": {"speakers": ["lounge-room", "outside"]}}, "key"),
    ("POST", "/api/action", {"action": "music.speakers", "args": {"speakers": ["lounge-room", "theatre"]}}, "key"),
    ("POST", "/api/action", {"action": "music.search_play", "args": {"query": "neil young"}}, "key"),
    ("POST", "/api/action", {"action": "tv.volume", "args": {"tv": "living-room", "delta": 2}}, "key"),
    ("POST", "/api/action", {"action": "tv.volume", "args": {"tv": "bedroom", "delta": 2}}, "key"),
    ("POST", "/api/action", {"action": "tv.mute", "args": {"tv": "living-room", "muted": True}}, "key"),
    ("POST", "/api/action", {"action": "tv.launch", "args": {"tv": "living-room", "app": "Netflix"}}, "key"),
    ("POST", "/api/action", {"action": "tv.play", "args": {"tv": "living-room", "title": "Bluey"}}, "key"),
    ("POST", "/api/action", {"action": "tv.launch", "args": {"tv": "frame", "app": "YouTube"}}, "key"),
    ("POST", "/api/action", {"action": "tv.power", "args": {"tv": "bedroom", "on": True}}, "key"),
    ("POST", "/api/action", {"action": "tv.power", "args": {"tv": "bedroom", "on": False}}, "key"),
    ("POST", "/api/action", {"action": "tv.art_mode", "args": {"tv": "frame", "on": True}}, "key"),
    ("POST", "/api/ask", {"text": ""}, "key"),
    ("POST", "/api/ask", {"text": "make the lounge warmer", "source": "wall"}, "key"),
    ("POST", "/api/ask", {"text": "hi"}, "none"),
    ("POST", "/api/pair", {"code": "123456", "name": "phone"}, "none"),
    ("POST", "/api/pair", b"nope", "none"),
    ("OPTIONS", "/api/state", None, "origin"),
    ("GET", "/api/state", None, "origin"),
    ("GET", "/api/state", None, "badorigin"),
    ("POST", "/api/ask/audio", b"", "audio"),
    ("POST", "/api/ask/audio", b"", "none"),
]

# index -> (fake status, real status, why)
KNOWN_DIFFS = {
    49: (403, 403, "same status; the fake also takes 000000, the real hub only a code made by `pair`"),
}


def headers(kind):
    return {"none": {}, "wrong": auth("wrong-wrong-wrong-wrong-wrong"), "key": auth(),
            "origin": {"Origin": ORIGIN, **auth()}, "badorigin": {"Origin": "http://evil.example", **auth()},
            "audio": {"Content-Type": "audio/webm", **auth()}}[kind]


def shape(x):
    if isinstance(x, dict):
        return {k: shape(v) for k, v in x.items()}
    if isinstance(x, list):
        return [shape(x[0])] if x else []
    if isinstance(x, bool):
        return "bool"
    if isinstance(x, (int, float)):
        return "number"
    if x is None:
        return None
    return type(x).__name__


def same_shape(a, b, path="state"):
    """Keys must match everywhere. Types must match where both sides have a value."""
    if a is None or b is None:
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        if set(a) != set(b):
            out.append(f"{path}: keys differ: fake {sorted(a)} real {sorted(b)}")
        for k in set(a) & set(b):
            out += same_shape(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if a and b:
            return same_shape(a[0], b[0], f"{path}[]")
        return []
    return [] if a == b else [f"{path}: fake {a} real {b}"]


@pytest.fixture
async def pair_of_hubs(home):
    fake = TestClient(TestServer(fake_hub.make_app([WALL_KEY], None, [ORIGIN])))
    await fake.start_server()
    real = await build(home, cors=(ORIGIN,), ask_factory=FakeAsk)
    yield fake, real
    await fake.close()
    await close(real)


async def send(client, req):
    method, path, body, kind = req
    h = headers(kind)
    if isinstance(body, bytes):
        r = await client.request(method, path, data=body, headers={"Content-Type": "application/json", **h})
    elif body is None:
        r = await client.request(method, path, headers=h)
    else:
        r = await client.request(method, path, json=body, headers=h)
    try:
        data = await r.json(content_type=None) if r.status != 204 else None
    except (ValueError, json.JSONDecodeError):
        data = None
    return r.status, data, r.headers


async def test_same_answers(pair_of_hubs):
    fake, real = pair_of_hubs
    problems = []
    for i, req in enumerate(REQUESTS):
        fs, fb, fh = await send(fake, req)
        rs, rb, rh = await send(real.client, req)
        label = f"#{i} {req[0]} {req[1]} {json.dumps(req[2]) if not isinstance(req[2], bytes) else req[2]!r}"
        if i in KNOWN_DIFFS:
            want_f, want_r, _ = KNOWN_DIFFS[i]
            if (fs, rs) != (want_f, want_r):
                problems.append(f"{label}: known diff changed: fake {fs} real {rs}")
            continue
        if fs != rs:
            problems.append(f"{label}: status fake {fs} real {rs} ({fb} / {rb})")
            continue
        if fb is not None and rb is not None:
            if set(fb) - {"fake"} != set(rb):
                problems.append(f"{label}: answer keys fake {sorted(fb)} real {sorted(rb)}")
            if fs in (400, 401) and fb.get("error") != rb.get("error"):
                problems.append(f"{label}: error words fake {fb.get('error')!r} real {rb.get('error')!r}")
            if fb.get("needs") != rb.get("needs"):
                problems.append(f"{label}: needs fake {fb.get('needs')} real {rb.get('needs')}")
            if "state" in fb and "state" in rb:
                problems += [f"{label}: {p}" for p in same_shape(shape(fb["state"]), shape(rb["state"]))]
            if req[1] == "/api/actions" and fs == 200:
                assert fb == rb
        if (fh.get("Access-Control-Allow-Origin") is None) != (rh.get("Access-Control-Allow-Origin") is None):
            problems.append(f"{label}: CORS header differs")
    assert not problems, "\n".join(problems)


async def test_same_state_shape_from_start(pair_of_hubs):
    fake, real = pair_of_hubs
    _, fb, _ = await send(fake, ("GET", "/api/state", None, "key"))
    _, rb, _ = await send(real.client, ("GET", "/api/state", None, "key"))
    assert same_shape(shape(fb["state"]), shape(rb["state"])) == []
    # every list has the same ids in the same order
    for part, key in (("aircon", "zones"), ("speakers", "devices"), ("tvs", "devices")):
        assert [x["id"] for x in fb["state"][part][key]] == [x["id"] for x in rb["state"][part][key]]


async def test_same_events_socket(pair_of_hubs):
    fake, real = pair_of_hubs
    for c in (fake, real.client):
        r = await c.get("/api/events?key=wrong")
        assert r.status == 401 and (await r.json())["error"] == "This needs the hub key."
    msgs = []
    for c in (fake, real.client):
        ws = await c.ws_connect(f"/api/events?key={WALL_KEY}")
        first = await ws.receive_json(timeout=3)
        await ws.send_json({"type": "ping"})
        pong = await ws.receive_json(timeout=3)
        msgs.append((first, pong))
        await ws.close()
    (f1, fp), (r1, rp) = msgs
    assert f1["type"] == r1["type"] == "state" and fp == rp == {"type": "pong"}
    assert same_shape(shape(f1["state"]), shape(r1["state"])) == []


async def test_same_device_down_answer(pair_of_hubs):
    fake, real = pair_of_hubs
    await fake.post("/fake/fail", json={"device": "aircon", "on": True})
    FakeAirtouch.instances[-1].drop()
    req = ("POST", "/api/action", {"action": "aircon.zone", "args": {"zone": "media", "on": False}}, "key")
    fs, fb, _ = await send(fake, req)
    rs, rb, _ = await send(real.client, req)
    assert fs == rs == 503
    assert fb == rb == {"ok": False, "error": "The aircon is not answering.", "device": "aircon"}
    _, fst, _ = await send(fake, ("GET", "/api/state", None, "key"))
    _, rst, _ = await send(real.client, ("GET", "/api/state", None, "key"))
    assert fst["state"]["aircon"]["available"] is rst["state"]["aircon"]["available"] is False


def test_shape_checker_catches_differences():
    a = {"aircon": {"set": 22, "zones": [{"id": "x", "on": True}]}}
    assert same_shape(shape(a), shape({"aircon": {"set": 22, "zones": [{"id": "x"}]}}))
    assert same_shape(shape(a), shape({"aircon": {"set": "22", "zones": [{"id": "x", "on": True}]}}))
    assert same_shape(shape(a), shape({"aircon": {"set": None, "zones": [{"id": "y", "on": False}]}})) == []
    assert len(REQUESTS) > 50 and REQUESTS[35][2]["args"]["speakers"] == ["lounge-room", "theatre"]
    assert REQUESTS[49][1] == "/api/pair"
