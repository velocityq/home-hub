"""The hub's web side: the routes in CONTRACT.md, the keys, CORS, the events socket, Ask and the wall."""
from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import re
import socket
import json
import logging
import os
import time

from aiohttp import WSMsgType, web
from aiohttp.abc import AbstractAccessLogger

import contract as C

from . import HUB_DIR
from . import config as cfgmod
from .errors import HubError, NeedsSpotify
from .spotify import shape_search

log = logging.getLogger("hub.web")
actions_log = logging.getLogger("hub.actions")

WALL_DIR = os.path.join(os.path.dirname(HUB_DIR), "wall")
AUDIO_MAX = 2 * 1024 * 1024
ASK_LIMIT, ASK_WINDOW = 30, 600          # asks per client per 10 minutes
AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave", "audio/mp4")
MAX_SOCKETS = 64
LOCAL = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
OPEN_PATHS = ("/api/health", "/api/pair")
# who asked, so the actions Ask runs are logged with the client's name (e.g. "wall via ask")
ASK_WHO = contextvars.ContextVar("ask_who", default="ask")
JSON_POSTS_EXEMPT = ("/api/ask/audio",)      # a recording, not JSON
# Every response. frame-ancestors: no other page may frame the wall (clickjacking).
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def allowed_hosts(cfg):
    """The names this hub answers to. An address typed as numbers is always fine; any other name must
    be this computer's own or one in config.json "allowed_hosts". This stops DNS rebinding: a web page
    on evil.example that re-points its own name at the hub gets "Host: evil.example" and is refused."""
    names = {"localhost"}
    try:
        h = socket.gethostname().lower().rstrip(".")
        names.add(h)
        names.add(h.split(".")[0] + ".local")
    except OSError:
        pass
    for h in cfg.get("allowed_hosts") or []:
        if isinstance(h, str) and h.strip():
            names.add(h.strip().lower().rstrip("."))
    return names


def host_ok(host_header, names):
    """True if the Host header is an IP address, or one of names. The port does not matter."""
    h = (host_header or "").strip().lower()
    if not h:
        return False
    if h.startswith("["):                               # [::1]:8790
        h = h[1:].split("]", 1)[0]
    elif h.count(":") == 1:
        h = h.rsplit(":", 1)[0]
    h = h.rstrip(".")
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return h in names


def err(status, text, **extra):
    return web.json_response({"ok": False, "error": text, **extra}, status=status)


def hub_error(e: HubError):
    return err(e.status, e.text, **e.extra)


class AccessLogger(AbstractAccessLogger):
    """One line per request: method, path WITHOUT the query (the events socket carries the key there),
    status, client name. Never the key."""

    def log(self, request, response, time_):
        if request.path.startswith("/api/") and request.path not in ("/api/health",):
            self.logger.info("%s %s %s %s %.0fms", request.remote, request.method, request.path,
                             response.status, time_ * 1000)

    @property
    def enabled(self):
        return self.logger.isEnabledFor(logging.INFO)


def make_app(hub, keys, cfg, wall_dir=WALL_DIR, ask_factory=None, personal=None):
    """hub: a Hub. keys: a config.Keys. ask_factory: for tests; normally ask.AskEngine is imported lazily.
    personal: a personal.Personal (tests pass their own)."""
    from .personal import Personal
    personal = personal or Personal(cfg)
    app = web.Application(client_max_size=3 * 1024 * 1024)
    app["personal"] = personal
    cors = set(cfg.get("cors_origins") or [])
    pair_state = {"fails": [], "lock": asyncio.Lock()}
    ask_state = {"engine": None, "tried": 0.0, "factory": ask_factory}

    # ---------- middlewares ----------
    @web.middleware
    async def cors_mw(request, handler):
        origin = request.headers.get("Origin")
        allowed = bool(origin) and origin in cors

        def add(headers):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
            headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        if request.method == "OPTIONS":
            resp = web.Response(status=204)
        else:
            try:
                resp = await handler(request)
            except web.HTTPException as e:
                if allowed:
                    add(e.headers)
                raise
        if allowed and not getattr(resp, "prepared", False):
            add(resp.headers)
        return resp

    @web.middleware
    async def auth_mw(request, handler):
        if request.method == "OPTIONS":
            return await handler(request)
        p = request.path
        if p.startswith("/api/") and p not in OPEN_PATHS and p != "/api/events":
            h = request.headers.get("Authorization", "")
            who = keys.who(h[7:].strip()) if h.startswith("Bearer ") else None
            if who is None:
                return err(401, "This needs the hub key.")
            request["client"] = who
        return await handler(request)

    hosts = allowed_hosts(cfg)

    @web.middleware
    async def guard_mw(request, handler):
        """Outermost: the Host check (DNS rebinding) and the security headers on every answer."""
        if not host_ok(request.host, hosts):
            log.info("refused a request for host %r (add it to allowed_hosts in config.json if it is yours)",
                     (request.host or "")[:80])
            resp = err(421, "This hub does not answer to that name.")
        else:
            try:
                resp = await handler(request)
            except web.HTTPException as e:
                e.headers.update(SECURITY_HEADERS)
                raise
        if not getattr(resp, "prepared", False):
            for k, v in SECURITY_HEADERS.items():
                resp.headers.setdefault(k, v)
        return resp

    @web.middleware
    async def json_mw(request, handler):
        """A POST to /api/ must say it is JSON (a recording for /api/ask/audio). A plain web form cannot
        send that without asking first, so no other page can post to the hub behind your back."""
        if (request.method == "POST" and request.path.startswith("/api/")
                and request.path not in JSON_POSTS_EXEMPT and request.content_type != "application/json"):
            return err(415, "Send JSON (Content-Type: application/json).")
        return await handler(request)

    app.middlewares.append(guard_mw)
    app.middlewares.append(cors_mw)
    app.middlewares.append(auth_mw)
    app.middlewares.append(json_mw)

    # ---------- routes ----------
    async def health(_):
        return web.json_response({"ok": True, "version": C.API_VERSION})

    async def state(_):
        return web.json_response({"ok": True, "state": hub.state()})

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
            st = await hub.run(body.get("action"), body.get("args"), who=request.get("client", "?"))
        except HubError as e:
            return hub_error(e)
        return web.json_response({"ok": True, "state": st})

    async def events(request):
        key = request.query.get("key")
        if not key:
            h = request.headers.get("Authorization", "")
            key = h[7:].strip() if h.startswith("Bearer ") else None
        who = keys.who(key)
        if who is None:
            return err(401, "This needs the hub key.")
        if len(hub.sockets) >= MAX_SOCKETS:
            return err(503, "Too many screens are connected.")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024)
        await ws.prepare(request)
        hub.sockets.add(ws)
        log.info("events: %s connected (%d open)", who, len(hub.sockets))
        try:
            await ws.send_str(json.dumps({"type": "state", "state": hub.state()}, default=str))
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        if json.loads(msg.data).get("type") == "ping":
                            await ws.send_str(json.dumps({"type": "pong"}))
                    except Exception:
                        pass
        finally:
            hub.sockets.discard(ws)
            log.info("events: %s left", who)
        return ws

    # ---------- ask ----------
    async def engine():
        if ask_state["engine"] is not None:
            return ask_state["engine"]
        if time.time() - ask_state["tried"] < 10:
            return None
        ask_state["tried"] = time.time()
        try:
            factory = ask_state["factory"]
            if factory is None:
                from ask import AskEngine as factory   # hub/ask/, built by part C
            conf = dict(cfg.get("ask") or {})
            conf.setdefault("home", cfgmod.home_dir())

            async def get_state():
                return hub.state()

            async def run_action(action, args):
                return await hub.run_for_ask(action, args, source=ASK_WHO.get())
            ask_state["engine"] = factory(get_state, run_action, conf)
            log.info("ask: engine loaded")
        except Exception as e:
            log.info("ask: not ready (%s)", type(e).__name__)
            return None
        return ask_state["engine"]

    def _source(v):
        return v.strip()[:40] if isinstance(v, str) and v.strip() else "unknown"

    def _answer(res):
        if not isinstance(res, dict):
            return err(503, "Ask gave no answer.")
        if res.get("ok") is False:
            # The engine says ok:false only for an unusable request (400), or when speech to text
            # itself failed or is not set up (503).
            text = str(res.get("error") or "Ask could not do that.")
            status = 503 if res.get("device") or "speech to text" in text.lower() else 400
            return err(status, text, **({"device": res["device"]} if res.get("device") else {}))
        return web.json_response({**res, "ok": True})

    ask_hits: dict[str, list[float]] = {}

    def ask_limited(request):
        """At most ASK_LIMIT asks per client in ASK_WINDOW seconds, so a stuck client or a stolen key
        cannot use up the owner's Claude plan."""
        who = request.get("client", "?")
        now = time.monotonic()
        hits = [t for t in ask_hits.get(who, []) if now - t < ASK_WINDOW]
        if len(hits) >= ASK_LIMIT:
            ask_hits[who] = hits
            actions_log.info("ask: %s is over the limit", who)
            return err(429, "That's a lot of questions in a short time. Wait a few minutes and try again.")
        hits.append(now)
        ask_hits[who] = hits
        return None

    async def ask(request):
        limited = ask_limited(request)
        if limited:
            return limited
        try:
            body = await request.json()
            text = C._text(body.get("text"), "text", 500)
        except Exception:
            return err(400, "Send some text to ask.")
        eng = await engine()
        if eng is None:
            return err(503, "Ask is not ready yet.")
        source = _source(body.get("source"))
        ASK_WHO.set(f"{request.get('client', '?')} via ask ({source})")
        actions_log.info("ask (text, %d chars) by %s from %s", len(text), request.get("client", "?"), source)
        try:
            res = await eng.ask_text(text, source)
        except HubError as e:
            return hub_error(e)
        except Exception:
            log.exception("ask failed")
            return err(503, "Ask is not working right now.")
        return _answer(res)

    async def ask_audio(request):
        limited = ask_limited(request)
        if limited:
            return limited
        if request.content_length is not None and request.content_length > AUDIO_MAX:
            return err(400, "The recording is too big (at most 2 MB).")
        mime = (request.content_type or "").split(";")[0].strip().lower()
        if mime not in AUDIO_TYPES:
            return err(400, "Send the recording as audio/webm, audio/ogg, audio/wav or audio/mp4.")
        data = bytearray()
        async for chunk in request.content.iter_chunked(64 * 1024):
            data.extend(chunk)
            if len(data) > AUDIO_MAX:
                return err(400, "The recording is too big (at most 2 MB).")
        source = _source(request.query.get("source"))
        if not data:
            return web.json_response({"ok": True, "heard": "", "reply": "I didn't catch that.", "actions": [],
                                      "via": "none"})
        eng = await engine()
        if eng is None:
            return err(503, "Ask is not ready yet.")
        ASK_WHO.set(f"{request.get('client', '?')} via ask ({source})")
        actions_log.info("ask (audio, %d bytes) by %s from %s", len(data), request.get("client", "?"), source)
        try:
            res = await eng.ask_audio(bytes(data), mime, source)
        except HubError as e:
            return hub_error(e)
        except Exception:
            log.exception("ask audio failed")
            return err(503, "Ask is not working right now.")
        return _answer(res)

    # ---------- pairing ----------
    async def pair(request):
        now = time.time()
        async with pair_state["lock"]:
            fails = [t for t in pair_state["fails"] if now - t < 600]
            pair_state["fails"] = fails
            if len(fails) >= 20:
                return err(429, "Too many tries. Make a new code.")
            try:
                body = await request.json()
            except Exception:
                return err(400, "Send a code.")
            if not isinstance(body, dict):
                return err(400, "Send a code.")
            code = body.get("code")
            name = body.get("name") if isinstance(body.get("name"), str) else "device"
            if cfgmod.check_pair_code(code if isinstance(code, str) else ""):
                final, key = keys.add(name or "device")
                actions_log.info("pair: new client %s from %s", final, request.remote)
                return web.json_response({"ok": True, "key": key, "name": final})
            pair_state["fails"].append(now)
            actions_log.info("pair: wrong code from %s", request.remote)
            # slow down: every wrong try waits longer (up to 5 s), holding the lock so tries queue up
            await asyncio.sleep(min(5.0, 0.5 * len(pair_state["fails"])))
            return err(403, "That code is wrong or has run out.")

    # ---------- spotify ----------
    def page(text, status=200):
        html = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                "<title>Home hub</title><body style='font:18px system-ui;max-width:40em;margin:3em auto'>"
                f"{text}</body>")
        return web.Response(text=html, content_type="text/html", status=status)

    async def spotify_login(request):
        if request.remote not in LOCAL:
            return err(403, "Link Spotify on the iMac itself.")
        sp = hub.spotify
        url = sp.login_url() if sp else None
        if not url:
            return page("<h1>Link Spotify</h1><p>One time set up, about 2 minutes.</p>"
                        "<p>1. Go to <a href='https://developer.spotify.com/dashboard'>developer.spotify.com/dashboard</a>, "
                        "log in, press <b>Create app</b>. Name: Home hub. Redirect URI: "
                        "<code>http://127.0.0.1:8790/spotify/callback</code>. Tick <b>Web API</b>. Save.</p>"
                        "<p>2. Open the app's Settings and copy the <b>Client ID</b> (it is not a secret).</p>"
                        "<p>3. Paste it here:</p>"
                        "<form method=post action='/spotify/client'><input name=client_id size=40 autofocus "
                        "style='font:18px monospace;padding:8px'> <button style='font:18px system-ui;padding:8px 16px'>Continue</button></form>"
                        "<p>Then Spotify asks you to press <b>Agree</b>. That is all.</p>", 409)
        raise web.HTTPFound(url)

    async def spotify_client(request):
        if request.remote not in LOCAL:
            return err(403, "Link Spotify on the iMac itself.")
        origin = request.headers.get("Origin")
        if origin and not re.match(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$", origin):
            return err(403, "Not from this page.")
        form = await request.post()
        cid = str(form.get("client_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9]{20,64}", cid):
            return page("<h1>That does not look like a Client ID</h1><p>It is about 32 letters and numbers. "
                        "<a href='/spotify/login'>Try again</a>.</p>", 400)
        cfgmod.write_json(cfgmod.path("spotify.json"), {"client_id": cid})
        raise web.HTTPFound("/spotify/login")

    async def spotify_callback(request):
        if request.remote not in LOCAL:
            return err(403, "Link Spotify on the iMac itself.")
        q = request.query
        if q.get("error"):
            return page(f"<h1>Spotify was not linked</h1><p>Spotify said: {_esc(q.get('error'))}.</p>", 409)
        try:
            await hub.spotify.finish_login(q.get("code", ""), q.get("state", ""))
        except HubError as e:
            return page(f"<h1>Spotify was not linked</h1><p>{_esc(e.text)}</p>", 409)
        hub.changed()
        return page("<h1>Spotify is linked</h1><p>You can close this page.</p>")

    # ---------- wall ----------
    def wall_file(rel):
        parts = rel.replace("\\", "/").split("/")
        if any(x.startswith(".") or x == "tests" for x in parts):     # no hidden files, no test shots
            return None
        base = os.path.realpath(wall_dir)
        p = os.path.realpath(os.path.join(base, rel))
        if not (p == base or p.startswith(base + os.sep)) or not os.path.isfile(p):
            return None
        return p

    async def wall_index(_):
        p = wall_file("index.html")
        if not p:
            return web.Response(text="The wall screen is not installed yet.", status=503)
        return web.FileResponse(p, headers={"Cache-Control": "no-cache"})

    async def wall_static(request):
        rel = request.match_info.get("path", "")
        p = wall_file(rel) if rel else None
        if not p:
            raise web.HTTPNotFound(text="Not found.")
        return web.FileResponse(p, headers={"Cache-Control": "no-cache"})

    # ---------- personal views (Face ID on the tablet sends a name, never a picture) ----------
    async def presence(request):
        try:
            body = await request.json()
        except Exception:
            return err(400, "The request was not valid JSON.")
        if not isinstance(body, dict):
            return err(400, "The request must be an object.")
        try:
            p = personal.set_presence(body.get("who"), body.get("how"), request.get("client", "?"))
        except ValueError as e:
            return err(400, f"Not a valid presence: {e}.")
        return web.json_response({"ok": True, "presence": p})

    async def home(_):
        """What the wall needs to know about this house that is not device state: the people with a
        card (names only) and the place name shown under the inside temperature. Both from config.json."""
        return web.json_response({"ok": True, "people": list(personal.people), "place": personal.place})

    async def personal_card(request):
        try:
            card = await personal.card(request.match_info["person"])
        except KeyError:
            return err(404, "There is no such person on this hub.")
        return web.json_response({"ok": True, "card": card})

    # ---------- the music view (Spotify library, search, main playlist, shuffle) ----------
    def need_spotify():
        if not (hub.spotify and hub.spotify.linked):
            raise NeedsSpotify("Spotify is not linked yet. Link it on the iMac to use the music view.")
        return hub.spotify

    async def music_library(request):
        try:
            lib = await need_spotify().library(force=request.query.get("fresh") == "1")
        except HubError as e:
            return hub_error(e)
        return web.json_response({"ok": True, "library": lib})

    async def music_search(request):
        q = (request.query.get("q") or "").strip()
        if not q:
            return web.json_response({"ok": True, "results": {"tracks": [], "artists": [], "albums": [], "playlists": []}})
        if len(q) > 120:
            return err(400, "Search for something shorter (at most 120 characters).")
        try:
            res = await need_spotify().search(q, limit=6)
        except HubError as e:
            return hub_error(e)
        return web.json_response({"ok": True, "results": shape_search(res)})

    async def music_main(request):
        try:
            body = await request.json()
        except Exception:
            return err(400, "The request was not valid JSON.")
        pid = body.get("playlist") if isinstance(body, dict) else None
        if not isinstance(pid, str) or not re.fullmatch(r"[A-Za-z0-9]{10,40}", pid):
            return err(400, "Pick a playlist.")
        try:
            sp = need_spotify()
            lib = await sp.library()
            if pid not in {p["id"] for p in lib["playlists"]}:
                return err(404, "That playlist is not in his Spotify.")
            sp.set_main(pid)
            lib = await sp.library(force=True)
        except HubError as e:
            return hub_error(e)
        actions_log.info("music main playlist set by %s", request.get("client", "?"))
        return web.json_response({"ok": True, "library": lib})

    async def music_shuffle(request):
        try:
            body = await request.json()
        except Exception:
            return err(400, "The request was not valid JSON.")
        on = body.get("on") if isinstance(body, dict) else None
        if not isinstance(on, bool):
            return err(400, "on must be true or false.")
        try:
            sp = need_spotify()
            await sp.shuffle(on)
            await sp.refresh_player()
        except HubError as e:
            return hub_error(e)
        hub.changed()
        return web.json_response({"ok": True, "state": hub.state()})

    async def api_missing(_):
        return err(404, "There is no such thing on the hub.")

    r = app.router
    r.add_get("/api/health", health)
    r.add_get("/api/state", state)
    r.add_get("/api/actions", actions)
    r.add_post("/api/action", action)
    r.add_get("/api/events", events)
    r.add_post("/api/ask", ask)
    r.add_post("/api/ask/audio", ask_audio)
    r.add_post("/api/pair", pair)
    r.add_get("/api/music/library", music_library)
    r.add_get("/api/music/search", music_search)
    r.add_post("/api/music/main", music_main)
    r.add_post("/api/music/shuffle", music_shuffle)
    r.add_post("/api/presence", presence)
    r.add_get("/api/home", home)
    r.add_get("/api/personal/{person}", personal_card)
    r.add_route("*", "/api/{tail:.*}", api_missing)
    r.add_get("/spotify/login", spotify_login)
    r.add_get("/spotify/callback", spotify_callback)
    r.add_post("/spotify/client", spotify_client)
    r.add_get("/", wall_index)
    r.add_get("/wall/{path:.*}", wall_static)
    r.add_get("/{path:.*}", wall_static)

    async def on_startup(_):
        await hub.start()

    async def on_cleanup(_):
        await hub.stop()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def _esc(s):
    import html
    return html.escape(str(s or ""))
