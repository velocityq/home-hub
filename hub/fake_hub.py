"""A fake home hub that follows CONTRACT.md exactly, with pretend devices in memory.

Every part is built and tested against this first. Nothing here touches a real device.

    hub/.venv/bin/python hub/fake_hub.py --port 8795 --key testkey [--wall wall]

Extra test-only routes (no key needed, only on the fake):
    POST /fake/fail   {"device": "aircon"|"speakers"|"tvs", "on": true}   make a device group unavailable
    POST /fake/reset  {}                                                   back to the starting state
    GET  /fake/log                                                         every action received
    POST /fake/groups {"groups": [{"members": ["lounge-room", "theatre"]}]} set the speaker groups
"""
import argparse
import asyncio
import copy
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone

from aiohttp import WSMsgType, web

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract as C  # noqa: E402

ZONE_NAMES = {"living": "Living", "media": "Media", "rumpus": "Rumpus", "master-bed": "Master Bed",
              "bed-2": "Bed 2", "bed-3": "Bed 3", "bed-4": "Bed 4"}
ZONE_TEMPS = [23.6, 24.2, 23.8, 24.8, 24.1, 23.9, 24.6]
ZONE_ON = [False, True, False, True, False, True, False]


def start_state():
    s = copy.deepcopy(C.EXAMPLE_STATE)
    s["aircon"]["zones"] = [{"id": z, "name": ZONE_NAMES[z], "on": on, "temp": t, "open": 100 if on else 0}
                            for z, t, on in zip(C.ZONES, ZONE_TEMPS, ZONE_ON)]
    return s


class Fake:
    def __init__(self, keys):
        self.keys = set(keys)
        self.state = start_state()
        self.fail = set()
        self.log = []
        self.sockets = set()
        self.pair_tries = 0
        self.started = time.time()

    # ---- helpers ----
    def stamp(self):
        self.state["updated"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        for dev in ("aircon", "speakers", "tvs", "lights"):
            self.state[dev]["available"] = dev not in self.fail

    async def broadcast(self):
        self.stamp()
        msg = json.dumps({"type": "state", "state": self.state})
        for ws in list(self.sockets):
            try:
                await ws.send_str(msg)
            except Exception:
                self.sockets.discard(ws)

    def authed(self, request):
        h = request.headers.get("Authorization", "")
        return h.startswith("Bearer ") and h[7:] in self.keys

    # ---- the pretend devices ----
    def apply(self, action, a):
        s = self.state
        group = action.split(".")[0]
        dev = {"aircon": "aircon", "music": "speakers", "speakers": "speakers", "tv": "tvs", "lights": "lights"}[group]
        if dev in self.fail:
            raise DeviceDown(dev)
        ac, sp, tv = s["aircon"], s["speakers"], s["tvs"]
        if group == "lights":
            rows = [d for d in s["lights"]["devices"] if a["light"] in (d["id"], C.LIGHT_ALL)]
            if not rows:
                raise NoLight()
            if action in ("lights.schedule", "lights.unschedule"):
                if a["light"] == C.LIGHT_ALL:
                    raise NoLight("Pick one light for a schedule.")
                sch = rows[0].setdefault("schedules", [])
                old = next((x for x in sch if x["id"] == a.get("schedule")), None)
                if a.get("schedule") and old is None:
                    raise NoLight("That schedule is not there any more.")
                if action == "lights.unschedule":
                    sch.remove(old)
                    return
                new = dict(old or {"id": secrets.token_hex(3), "fade": 0, "enabled": True})
                new.update({k: a[k] for k in ("time", "days", "do", "brightness", "kelvin", "fade", "enabled") if k in a})
                on = new["do"] == "on"
                new["brightness"] = (new.get("brightness") or 100) if on else None
                new["kelvin"] = (new.get("kelvin") or 2700) if on else None
                if old:
                    sch[sch.index(old)] = new
                else:
                    sch.append(new)
                sch.sort(key=lambda x: x["time"])
                return
            for d in rows:
                if action == "lights.power":
                    d["on"] = a["on"]
                else:
                    d["on"] = True
                    if action == "lights.brightness":
                        d["brightness"] = a["value"]
                    elif action == "lights.white":
                        d["kelvin"], d["color"] = a["kelvin"], None
                    elif action == "lights.color":
                        d["color"], d["kelvin"] = a["color"], None
        elif action == "aircon.power":
            ac["power"] = a["on"]
        elif action == "aircon.set_temp":
            ac["set"] = a["value"]
        elif action == "aircon.nudge":
            ac["set"] = max(C.TEMP_MIN, min(C.TEMP_MAX, ac["set"] + a["delta"]))
        elif action == "aircon.mode":
            ac["mode"], ac["power"] = a["mode"], True
        elif action == "aircon.fan":
            have = ac["fan_speeds"]
            ac["fan"] = a["speed"] if a["speed"] in have else min(
                have, key=lambda f: abs(C.FAN_SPEEDS.index(f) - C.FAN_SPEEDS.index(a["speed"])))
        elif action == "aircon.zone":
            z = next(z for z in ac["zones"] if z["id"] == a["zone"])
            z["on"], z["open"] = a["on"], 100 if a["on"] else 0
        elif action == "aircon.zones_all":
            for z in ac["zones"]:
                z["on"], z["open"] = a["on"], 100 if a["on"] else 0
        elif action in ("music.play", "music.pause", "music.next", "music.previous"):
            now = sp["now"]
            if now is None:
                raise NothingPlaying()
            if action == "music.play":
                now["playing"] = True
            elif action == "music.pause":
                now["playing"] = False
            elif action == "music.next":
                now.update(title="Holocene", artist="Bon Iver", album="Bon Iver", duration=337, position=0)
            else:
                now["position"] = 0
        elif action == "music.speakers":
            if sp["now"] is None:
                raise NothingPlaying()
            if len(a["speakers"]) > 1 and not any(set(g["members"]) == set(a["speakers"]) for g in sp["groups"]):
                raise NoGroup()
            sp["now"]["on"] = a["speakers"]
            for d in sp["devices"]:
                d["in_use"] = d["id"] in a["speakers"]
        elif action == "music.start":
            if not sp["spotify"]["linked"]:
                raise NeedsSpotify()
            on = a.get("speakers") or (sp["now"] or {}).get("on") or ["lounge-room"]
            sp["now"] = {"title": "Started from the wall", "artist": "Various", "album": None, "art": None,
                         "duration": 200, "position": 0, "playing": True, "source": "spotify", "on": on}
            for d in sp["devices"]:
                d["in_use"] = d["id"] in on
        elif action == "music.search_play":
            if not sp["spotify"]["linked"]:
                raise NeedsSpotify()
            on = a.get("speakers") or (sp["now"] or {}).get("on") or ["lounge-room"]
            sp["now"] = {"title": f"Top result for {a['query']}", "artist": "Various", "album": None, "art": None,
                         "duration": 200, "position": 0, "playing": True, "source": "spotify", "on": on}
            for d in sp["devices"]:
                d["in_use"] = d["id"] in on
        elif action == "speakers.volume":
            for d in sp["devices"]:
                if a["speaker"] == d["id"] or (a["speaker"] == "all" and d["in_use"]):
                    d["volume"] = a["value"]
        elif action.startswith("tv."):
            t = next(t for t in tv["devices"] if t["id"] == a["tv"])
            if action == "tv.power":
                t["power"] = "on" if a["on"] else "off"
                if a["on"]:
                    t["volume"] = t["volume"] if t["volume"] is not None else 15
                    t["muted"] = False
                    t["app"] = t["app"] or "Live TV"
                else:
                    t["app"] = None
            else:
                if t["power"] != "on" and action != "tv.art_mode":
                    raise TvOff(t["name"])
                if action == "tv.volume":
                    t["volume"] = max(0, min(100, (t["volume"] or 0) + a["delta"]))
                    t["muted"] = False
                elif action == "tv.mute":
                    t["muted"] = a["muted"]
                elif action == "tv.launch":
                    t["app"] = a["app"]
                elif action == "tv.play":
                    t["app"] = "Netflix"
                elif action == "tv.art_mode":
                    t["art_mode"] = a["on"]
                elif action == "tv.key" and a["key"] == "home":
                    t["app"] = "Home"


class DeviceDown(Exception):
    def __init__(self, dev):
        self.dev = dev
        names = {"aircon": "The aircon is not answering.", "speakers": "The speakers are not answering.",
                 "tvs": "The TV bridge is not answering.", "lights": "The lights are not answering."}
        super().__init__(names[dev])


class NoLight(Exception):
    def __init__(self, text="That is not one of this house's lights."):
        super().__init__(text)


class NothingPlaying(Exception):
    def __init__(self):
        super().__init__("Nothing is playing. Start some music first.")


class NoGroup(Exception):
    def __init__(self):
        super().__init__("There is no speaker group for those speakers yet. Make one in the Google Home app.")


class NeedsSpotify(Exception):
    def __init__(self):
        super().__init__("Spotify is not linked yet.")


class TvOff(Exception):
    def __init__(self, name):
        super().__init__(f"The {name} TV is off. Turn it on first.")


def err(status, text, **extra):
    return web.json_response({"ok": False, "error": text, **extra}, status=status)


PEOPLE = ["Sam", "Alex"]          # made up: the fake hub's people and place (GET /api/home)
PLACE = "Riverside"


def make_app(keys, wall_dir=None, cors=(), people=None, place=PLACE):
    fake = Fake(keys)
    fake.people = list(PEOPLE if people is None else people)
    app = web.Application(client_max_size=3 * 1024 * 1024)
    app["fake"] = fake
    cors = set(cors)

    @web.middleware
    async def cors_mw(request, handler):
        """Only listed origins get CORS headers (never "*"), the same rule as the real hub."""
        origin = request.headers.get("Origin")
        if request.method == "OPTIONS":
            resp = web.Response(status=204)
        else:
            resp = await handler(request)
        if origin and origin in cors:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    app.middlewares.append(cors_mw)

    @web.middleware
    async def auth(request, handler):
        if request.method == "OPTIONS":
            return await handler(request)
        p = request.path
        open_paths = ("/api/health", "/api/pair")
        if p.startswith("/api/") and p not in open_paths and p != "/api/events" and not fake.authed(request):
            return err(401, "This needs the hub key.")
        return await handler(request)

    app.middlewares.append(auth)

    async def health(_):
        return web.json_response({"ok": True, "version": C.API_VERSION, "fake": True})

    async def state(_):
        fake.stamp()
        return web.json_response({"ok": True, "state": fake.state})

    async def actions(_):
        return web.json_response({"ok": True, "actions": C.describe_actions()})

    async def action(request):
        try:
            body = await request.json()
        except Exception:
            return err(400, "The request was not valid JSON.")
        if not isinstance(body, dict):
            return err(400, "The request must be an object.")
        try:
            name, args = C.validate(body.get("action"), body.get("args"))
        except C.ContractError as e:
            return err(400, str(e))
        fake.log.append({"action": name, "args": args, "at": time.time()})
        await asyncio.sleep(0.08)          # a real device takes a moment
        try:
            fake.apply(name, args)
        except DeviceDown as e:
            return err(503, str(e), device=e.dev)
        except NeedsSpotify as e:
            return err(409, str(e), needs="spotify")
        except (NothingPlaying, TvOff, NoGroup, NoLight) as e:
            return err(409, str(e))
        await fake.broadcast()
        return web.json_response({"ok": True, "state": fake.state})

    async def events(request):
        if request.query.get("key") not in fake.keys:
            return err(401, "This needs the hub key.")
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        fake.sockets.add(ws)
        fake.stamp()
        await ws.send_str(json.dumps({"type": "state", "state": fake.state}))
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    if json.loads(msg.data).get("type") == "ping":
                        await ws.send_str(json.dumps({"type": "pong"}))
                except Exception:
                    pass
        fake.sockets.discard(ws)
        return ws

    async def ask(request):
        try:
            body = await request.json()
            text = C._text(body.get("text"), "text", 500)
        except Exception:
            return err(400, "Send some text to ask.")
        return web.json_response({"ok": True, "heard": text, "reply": f"(fake hub) I heard: {text}",
                                  "actions": [], "via": "none"})

    async def ask_audio(request):
        data = await request.read()
        if not data:
            return web.json_response({"ok": True, "heard": "", "reply": "I didn't catch that.", "actions": [], "via": "none"})
        return web.json_response({"ok": True, "heard": f"(fake hub) {len(data)} bytes of audio",
                                  "reply": "(fake hub) Speech to text is not part of the fake.", "actions": [], "via": "none"})

    async def pair(request):
        fake.pair_tries += 1
        if fake.pair_tries > 20:
            return err(429, "Too many tries. Make a new code.")
        try:
            body = await request.json()
        except Exception:
            return err(400, "Send a code.")
        if body.get("code") != "000000":
            return err(403, "That code is wrong or has run out.")
        key = "fake-paired-key"
        fake.keys.add(key)
        return web.json_response({"ok": True, "key": key, "name": str(body.get("name") or "device")[:40]})

    async def presence(request):
        try:
            body = await request.json()
        except Exception:
            return err(400, "The request was not valid JSON.")
        if not isinstance(body, dict) or body.get("who") not in (*fake.people, None) or body.get("how") not in ("face", "tap"):
            return err(400, "Not a valid presence.")
        fake.presence = {"who": body.get("who"), "how": body.get("how") if body.get("who") else None, "at": time.time()}
        fake.log.append({"presence": fake.presence["who"], "how": body.get("how")})
        return web.json_response({"ok": True, "presence": fake.presence})

    async def home(_):
        return web.json_response({"ok": True, "people": fake.people, "place": place})

    async def personal_card(request):
        person = request.match_info["person"]
        if person not in fake.people:
            return err(404, "There is no such person on this hub.")
        now = datetime.now().astimezone()
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if fake.people and person == fake.people[0]:
            events = [{"title": "Team meeting", "start": (day.replace(hour=23, minute=0) if now.hour < 23 else now).isoformat(), "allDay": False, "calendar": "Work"},
                      {"title": "Dentist", "start": (day + __import__("datetime").timedelta(days=1, hours=10)).isoformat(), "allDay": False, "calendar": "Work"},
                      {"title": "Bin night", "start": (day + __import__("datetime").timedelta(days=2)).date().isoformat(), "allDay": True, "calendar": "Work"}]
            sources = [{"name": "Work", "connected": True, "note": None}]
        else:
            events, sources = [], []
        return web.json_response({"ok": True, "card": {"person": person,
            "calendar": {"sources": sources, "events": events, "more": 0, "days": 7},
            "ring": {"connected": False, "note": "Not connected yet"}, "parcels": {"connected": False, "note": "Not connected yet"}}})

    async def fake_fail(request):
        body = await request.json()
        (fake.fail.add if body.get("on") else fake.fail.discard)(body["device"])
        await fake.broadcast()
        return web.json_response({"ok": True, "fail": sorted(fake.fail)})

    async def fake_reset(_):
        fake.state, fake.fail = start_state(), set()
        await fake.broadcast()
        return web.json_response({"ok": True})

    async def fake_log(_):
        return web.json_response({"ok": True, "log": fake.log})

    async def fake_groups(request):
        """Set the Google Home speaker groups the fake knows, e.g. all four once they exist."""
        body = await request.json()
        fake.state["speakers"]["groups"] = [
            {"id": "+".join(m), "name": g.get("name") or " + ".join(m), "members": list(m)}
            for g in body.get("groups", []) for m in [g["members"]]]
        await fake.broadcast()
        return web.json_response({"ok": True})

    LIB = {"playlists": [
        {"id": "FakeMainPlaylist000001", "uri": "spotify:playlist:FakeMainPlaylist000001", "name": "Friday Night", "image": "https://i.scdn.co/image/a", "mine": True, "owner": "Sam"},
        {"id": "FakePlaylist0000000002", "uri": "spotify:playlist:FakePlaylist0000000002", "name": "EDM Nostalgia", "image": "https://i.scdn.co/image/b", "mine": False, "owner": "Someone"},
        {"id": "FakePlaylist0000000003", "uri": "spotify:playlist:FakePlaylist0000000003", "name": "Australian Classics", "image": "https://i.scdn.co/image/c", "mine": False, "owner": "Spotify"},
        {"id": "FakePlaylist0000000004", "uri": "spotify:playlist:FakePlaylist0000000004", "name": "Cocktail hour", "image": None, "mine": False, "owner": "Spotify"}],
        "recent": [{"uri": "spotify:track:aaaaaaaaaaaa", "name": "Don't Call It Love", "sub": "MOTU", "image": "https://i.scdn.co/image/d"},
                   {"uri": "spotify:track:bbbbbbbbbbbb", "name": "Almost Happy", "sub": "Someone", "image": "https://i.scdn.co/image/e"}],
        "user_id": "fakeuser", "main": "FakeMainPlaylist000001", "main_chosen": False,
        "discover": "spotify:playlist:FakeDiscoverWeekly0005"}

    def need_spotify():
        if not fake.state["speakers"]["spotify"]["linked"]:
            raise NeedsSpotify()

    async def music_library(_):
        try:
            need_spotify()
        except NeedsSpotify as e:
            return err(409, str(e), needs="spotify")
        return web.json_response({"ok": True, "library": LIB})

    async def music_search(request):
        try:
            need_spotify()
        except NeedsSpotify as e:
            return err(409, str(e), needs="spotify")
        q = (request.query.get("q") or "").strip()
        fake.log.append({"action": "search", "args": {"q": q}, "at": time.time()})
        none = {"tracks": [], "artists": [], "albums": [], "playlists": []}
        if q.lower() == "nothing":
            return web.json_response({"ok": True, "results": none})
        return web.json_response({"ok": True, "results": {
            "tracks": [{"uri": "spotify:track:cccccccccccc", "name": q.title(), "sub": "Artist One", "image": "https://i.scdn.co/image/f"}],
            "artists": [{"uri": "spotify:artist:dddddddddddd", "name": "Daft Punk", "sub": "Artist", "image": None}],
            "albums": [{"uri": "spotify:album:eeeeeeeeeeee", "name": "Discovery", "sub": "Daft Punk", "image": None}],
            "playlists": [{"uri": "spotify:playlist:ffffffffffff", "name": "This Is Daft Punk", "sub": "Spotify", "image": None}]}})

    async def music_main(request):
        body = await request.json()
        fake.log.append({"action": "main", "args": body, "at": time.time()})
        LIB["main"] = body.get("playlist")
        LIB["main_chosen"] = True
        return web.json_response({"ok": True, "library": LIB})

    async def music_shuffle(request):
        body = await request.json()
        fake.log.append({"action": "shuffle", "args": body, "at": time.time()})
        now = fake.state["speakers"]["now"]
        if now is None:
            return err(409, "Nothing is playing right now.")
        now["shuffle"] = bool(body.get("on"))
        await fake.broadcast()
        return web.json_response({"ok": True, "state": fake.state})

    async def fake_link_spotify(request):
        body = await request.json()
        sp = fake.state["speakers"]["spotify"]
        sp["linked"] = bool(body.get("linked", True))
        if body.get("idle"):
            fake.state["speakers"]["now"] = None
            for d in fake.state["speakers"]["devices"]:
                d["in_use"] = False
        if sp["linked"]:
            sp["last"] = "Holocene · Bon Iver"
            sp["playlists"] = [{"id": "37i9dQZF1DXcBWIGoYBM5M", "name": "Today's Top Hits"}, {"id": "37i9dQZF1DX4WYpdgoIcn6", "name": "Chill Hits"},
                               {"id": "37i9dQZF1DWXRqgorJj26U", "name": "Rock Classics"}, {"id": "37i9dQZF1DX0XUsuxWHRQd", "name": "RapCaviar"},
                               {"id": "37i9dQZF1DWTwnEm1IYyoj", "name": "Soft Pop Hits"}]
        else:
            sp.pop("last", None); sp.pop("playlists", None)
        await fake.broadcast()
        return web.json_response({"ok": True})

    r = app.router
    r.add_get("/api/health", health)
    r.add_get("/api/state", state)
    r.add_get("/api/actions", actions)
    r.add_post("/api/action", action)
    r.add_get("/api/events", events)
    r.add_post("/api/ask", ask)
    r.add_post("/api/ask/audio", ask_audio)
    r.add_post("/api/pair", pair)
    r.add_post("/api/presence", presence)
    r.add_get("/api/personal/{person}", personal_card)
    r.add_get("/api/home", home)
    r.add_post("/fake/fail", fake_fail)
    r.add_post("/fake/reset", fake_reset)
    r.add_get("/fake/log", fake_log)
    r.add_post("/fake/spotify", fake_link_spotify)
    r.add_get("/api/music/library", music_library)
    r.add_get("/api/music/search", music_search)
    r.add_post("/api/music/main", music_main)
    r.add_post("/api/music/shuffle", music_shuffle)
    r.add_post("/fake/groups", fake_groups)
    if wall_dir and os.path.isdir(wall_dir):
        async def index(_):
            return web.FileResponse(os.path.join(wall_dir, "index.html"))
        r.add_get("/", index)
        r.add_static("/wall/", wall_dir)
        r.add_static("/assets/", os.path.join(wall_dir, "assets"))
    return app


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8795)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--key", action="append", default=[], help="a client key (repeat for more)")
    ap.add_argument("--wall", help="serve this folder as the wall screen at /")
    ap.add_argument("--cors", action="append", default=[], help="an origin allowed to call the hub from a browser")
    a = ap.parse_args()
    web.run_app(make_app(a.key or ["testkey"], a.wall, a.cors), host=a.host, port=a.port, print=lambda *_: print(
        f"fake hub on http://{a.host}:{a.port}  keys: {', '.join(a.key or ['testkey'])}", flush=True))


if __name__ == "__main__":
    main()
