"""Spotify Web API, linked once with Authorization Code + PKCE (no client secret).

The owner makes a Spotify developer app with the redirect URI
http://127.0.0.1:8790/spotify/callback and puts its client id in ~/.home-hub/spotify.json:
    {"client_id": "..."}
Then opens http://127.0.0.1:8790/spotify/login on the iMac. Tokens go to
~/.home-hub/spotify-token.json (mode 600) and refresh by themselves.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import aiohttp

from . import config as cfgmod
from .errors import Conflict, DeviceDown, NeedsSpotify

log = logging.getLogger("hub.spotify")

SCOPES = ("user-read-playback-state user-modify-playback-state user-read-currently-playing "
          "user-read-recently-played playlist-read-private user-library-read")
API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
# Spotify's own made-for-you Discover Weekly playlists all start like this (his own one is found from what he played)
DISCOVER_PREFIX = "spotify:playlist:37i9dQZEVXc"


class Spotify:
    def __init__(self, cfg, on_change=lambda: None, api=API, accounts=ACCOUNTS):
        self.cfg = cfg
        self.on_change = on_change
        self.api_base = api.rstrip("/")
        self.accounts = accounts.rstrip("/")
        self.redirect_uri = cfg.get("spotify_redirect_uri") or "http://127.0.0.1:8790/spotify/callback"
        self.pending = {}            # state -> (verifier, expires)
        self.player = None           # last GET /me/player (dict) or None
        self.player_at = 0.0         # time.time() of that read
        self.session: aiohttp.ClientSession | None = None
        self._task = None
        self._refresh_lock = asyncio.Lock()
        self.last_error = None
        self.quick = {"playlists": [], "last": None}   # for the one tap music buttons
        self.quick_at = 0.0
        self._lib = None
        self._lib_at = 0.0

    # ---------- files ----------
    @property
    def client_id(self):
        d = cfgmod.read_json(cfgmod.path("spotify.json"), {}) or {}
        cid = d.get("client_id") if isinstance(d, dict) else None
        return cid.strip() if isinstance(cid, str) and cid.strip() else None

    def _token(self):
        t = cfgmod.read_json(cfgmod.path("spotify-token.json"))
        return t if isinstance(t, dict) and t.get("refresh_token") else None

    def _save_token(self, t):
        cfgmod.write_json(cfgmod.path("spotify-token.json"), t)

    @property
    def linked(self):
        return bool(self.client_id and self._token())

    # ---------- life ----------
    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
        self._task = asyncio.create_task(self._poll(), name="spotify")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self.session:
            await self.session.close()

    async def _poll(self):
        while True:
            wait = 15
            if self.linked:
                try:
                    await self.refresh_player()
                    if time.time() - self.quick_at > 600:
                        await self.refresh_quick()
                    self.last_error = None
                    wait = 3 if (self.player or {}).get("is_playing") else 8
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.last_error = type(e).__name__
                    log.info("spotify: poll failed: %s", type(e).__name__)
                    wait = 30
            elif self.player is not None:
                self.player = None
                self.on_change()
            await asyncio.sleep(wait)

    # ---------- linking (PKCE) ----------
    def login_url(self):
        cid = self.client_id
        if not cid:
            return None
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        now = time.time()
        self.pending = {s: v for s, v in self.pending.items() if v[1] > now}
        self.pending[state] = (verifier, now + 600)
        return f"{self.accounts}/authorize?" + urlencode({
            "client_id": cid, "response_type": "code", "redirect_uri": self.redirect_uri,
            "code_challenge_method": "S256", "code_challenge": challenge, "state": state, "scope": SCOPES})

    async def finish_login(self, code, state):
        item = self.pending.pop(state or "", None)
        if not item or item[1] < time.time():
            raise Conflict("That Spotify link has run out. Start again.")
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
                "client_id": self.client_id, "code_verifier": item[0]}
        t = await self._token_call(data)
        if not t.get("refresh_token"):
            raise Conflict("Spotify did not give a refresh token.")
        self._save_token(t)
        log.info("spotify: linked")
        await self.refresh_player()
        await self.refresh_quick()
        self.on_change()

    async def _token_call(self, data):
        async with self.session.post(f"{self.accounts}/api/token", data=data,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"}) as r:
            body = await r.json(content_type=None)
            if r.status != 200 or not isinstance(body, dict) or "access_token" not in body:
                log.warning("spotify: token call failed (%s)", r.status)
                raise NeedsSpotify("Spotify did not accept the link. Link it again on the iMac.")
        old = self._token() or {}
        return {"access_token": body["access_token"],
                "refresh_token": body.get("refresh_token") or old.get("refresh_token"),
                "expires_at": time.time() + int(body.get("expires_in", 3600)) - 60,
                "scope": body.get("scope", "")}

    async def _access(self, force=False):
        t = self._token()
        if not t or not self.client_id:
            raise NeedsSpotify()
        if not force and t.get("access_token") and t.get("expires_at", 0) > time.time():
            return t["access_token"]
        async with self._refresh_lock:
            t = self._token()
            if not force and t.get("access_token") and t.get("expires_at", 0) > time.time():
                return t["access_token"]
            nt = await self._token_call({"grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                                         "client_id": self.client_id})
            self._save_token(nt)
            return nt["access_token"]

    # ---------- Web API ----------
    async def call(self, method, path, params=None, json=None, _retry=True):
        tok = await self._access()
        try:
            async with self.session.request(method, self.api_base + path, params=params, json=json,
                                            headers={"Authorization": f"Bearer {tok}"}) as r:
                if r.status == 401 and _retry:
                    await self._access(force=True)
                    return await self.call(method, path, params, json, _retry=False)
                if r.status == 429 and _retry:
                    await asyncio.sleep(min(int(r.headers.get("Retry-After", "1") or 1), 5))
                    return await self.call(method, path, params, json, _retry=False)
                if r.status < 400 and (r.status in (202, 204) or r.content_length == 0):
                    return None
                try:
                    body = await r.json(content_type=None)
                except ValueError:
                    body = None
                if r.status >= 400:
                    msg = ((body or {}).get("error") or {}).get("message") if isinstance(body, dict) else None
                    reason = ((body or {}).get("error") or {}).get("reason") if isinstance(body, dict) else None
                    log.info("spotify: %s %s -> %s %s", method, path, r.status, reason or msg)
                    if r.status == 403 and reason == "PREMIUM_REQUIRED":
                        raise Conflict("Spotify says this needs Spotify Premium.")
                    if r.status == 404:
                        raise Conflict("Spotify has no active speaker right now. Pick a speaker and try again.")
                    raise Conflict(f"Spotify said no{': ' + msg if msg else ''}.")
                return body
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise DeviceDown("speakers", "Spotify is not answering.") from e

    async def refresh_player(self):
        p = await self.call("GET", "/me/player", params={"additional_types": "episode"})
        changed = _player_key(p) != _player_key(self.player)
        self.player, self.player_at = p, time.time()
        if changed:
            self.on_change()
        return p

    async def refresh_quick(self):
        """Playlists and the last played thing, for the one tap buttons. Never fails the poll."""
        self.quick_at = time.time()
        try:
            pl = await self.call("GET", "/me/playlists", params={"limit": "6"}) or {}
            rec = await self.call("GET", "/me/player/recently-played", params={"limit": "1"}) or {}
        except Conflict as e:
            log.info("spotify: quick lists unavailable: %s", e.text)
            return
        self.quick = {
            "playlists": [{"id": p["id"], "name": p.get("name") or "Playlist"} for p in (pl.get("items") or [])
                          if p and p.get("id")][:6],
            "last": self._last_of(rec)}
        self.on_change()

    @staticmethod
    def _last_of(rec):
        items = (rec or {}).get("items") or []
        if not items:
            return None
        t = items[0].get("track") or {}
        ctx = items[0].get("context") or {}
        return {"track_uri": t.get("uri"), "context_uri": ctx.get("uri"), "title": t.get("name"),
                "artist": ((t.get("artists") or [{}])[0]).get("name")}

    async def liked_uris(self, n=50):
        d = await self.call("GET", "/me/tracks", params={"limit": str(n)}) or {}
        return [x["track"]["uri"] for x in (d.get("items") or []) if x.get("track") and x["track"].get("uri")]

    async def devices(self):
        d = await self.call("GET", "/me/player/devices")
        return (d or {}).get("devices") or []

    async def transfer(self, device_id, play=True):
        await self.call("PUT", "/me/player", json={"device_ids": [device_id], "play": play})

    async def play(self, device_id=None, context_uri=None, uris=None):
        body = {}
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        await self.call("PUT", "/me/player/play", params={"device_id": device_id} if device_id else None,
                        json=body or None)

    async def pause(self):
        await self.call("PUT", "/me/player/pause")

    async def next(self):
        await self.call("POST", "/me/player/next")

    async def previous(self):
        await self.call("POST", "/me/player/previous")

    async def search(self, q, limit=5):
        return await self.call("GET", "/search", params={"q": q, "type": "track,artist,album,playlist",
                                                         "limit": str(limit)}) or {}

    async def shuffle(self, on):
        await self.call("PUT", "/me/player/shuffle", params={"state": "true" if on else "false"})

    # ---------- the music view: library, prefs, discover ----------
    def prefs(self):
        d = cfgmod.read_json(cfgmod.path("spotify-prefs.json"), {}) or {}
        return d if isinstance(d, dict) else {}

    def save_prefs(self, **kw):
        d = self.prefs()
        d.update(kw)
        cfgmod.write_json(cfgmod.path("spotify-prefs.json"), d)

    async def user_id(self):
        uid = self.prefs().get("user_id")
        if uid:
            return uid
        me = await self.call("GET", "/me") or {}
        uid = me.get("id")
        if uid:
            self.save_prefs(user_id=uid)
        return uid

    async def liked_context(self):
        """Liked Songs as a playable context, or None when Spotify will not tell us the user id."""
        try:
            uid = await self.user_id()
        except Conflict:
            uid = None
        return f"spotify:user:{uid}:collection" if uid else None

    async def library(self, force=False):
        """Everything the music view lists: playlists with cover art, Liked Songs, his main playlist,
        Discover Weekly (found from what he played lately, then remembered) and recently played."""
        if not force and self._lib and time.time() - self._lib_at < 60:
            return self._lib
        pl = await self.call("GET", "/me/playlists", params={"limit": "50"}) or {}
        uid = None
        try:
            uid = await self.user_id()
        except Conflict:
            pass
        rec = {}
        try:
            rec = await self.call("GET", "/me/player/recently-played", params={"limit": "50"}) or {}
        except Conflict:
            pass
        playlists = [{"id": p["id"], "uri": p.get("uri") or "spotify:playlist:" + p["id"], "name": p.get("name") or "Playlist",
                      "image": _img(p.get("images"), 300), "mine": bool(uid and (p.get("owner") or {}).get("id") == uid),
                      "owner": (p.get("owner") or {}).get("display_name")}
                     for p in (pl.get("items") or []) if p and p.get("id")]
        prefs = self.prefs()
        counts, recent, seen = {}, [], set()
        discover = prefs.get("discover")
        for it in rec.get("items") or []:
            t, ctx = it.get("track") or {}, (it.get("context") or {}).get("uri")
            if ctx:
                counts[ctx] = counts.get(ctx, 0) + 1
                if ctx.startswith(DISCOVER_PREFIX) and not discover:
                    discover = ctx
            if t.get("uri") and t["uri"] not in seen and len(recent) < 12:
                seen.add(t["uri"])
                recent.append({"uri": t["uri"], "name": t.get("name"), "sub": _artists(t),
                               "image": _img((t.get("album") or {}).get("images"), 120)})
        if discover and discover != prefs.get("discover"):
            self.save_prefs(discover=discover)
        ids = {p["uri"]: p for p in playlists}
        main = prefs.get("main")
        main_pl = next((p for p in playlists if p["id"] == main), None)
        if not main_pl:      # most played of his own playlists lately, else the first one he made
            played = sorted((p for p in playlists if p["mine"] and counts.get(p["uri"])), key=lambda p: -counts[p["uri"]])
            main_pl = (played or [p for p in playlists if p["mine"]] or playlists or [None])[0]
        self._lib_at = time.time()
        self._lib = {"playlists": playlists, "recent": recent, "user_id": uid,
                     "main": main_pl["id"] if main_pl else None, "main_chosen": bool(main and main_pl and main_pl["id"] == main),
                     "discover": discover}
        return self._lib

    def set_main(self, playlist_id):
        self.save_prefs(main=playlist_id)
        self._lib_at = 0.0


def _img(images, want=300):
    """The smallest image that is at least `want` wide (Spotify lists big to small), else the biggest."""
    imgs = [i for i in (images or []) if i and i.get("url")]
    if not imgs:
        return None
    sized = [i for i in imgs if i.get("width")]
    if sized:
        ok = [i for i in sized if i["width"] >= want]
        return (min(ok, key=lambda i: i["width"]) if ok else max(sized, key=lambda i: i["width"]))["url"]
    return imgs[0]["url"]


def _artists(item):
    return ", ".join(a.get("name", "") for a in (item or {}).get("artists") or [] if a) or None


def shape_search(res, per=6):
    """Spotify's search answer as one flat, small list the wall can draw. Nulls and gaps are dropped."""
    out = {"tracks": [], "artists": [], "albums": [], "playlists": []}
    for t in ((res.get("tracks") or {}).get("items") or [])[:per]:
        if t and t.get("uri"):
            out["tracks"].append({"uri": t["uri"], "name": t.get("name"), "sub": _artists(t),
                                  "image": _img((t.get("album") or {}).get("images"), 120)})
    for a in ((res.get("artists") or {}).get("items") or [])[:per]:
        if a and a.get("uri"):
            out["artists"].append({"uri": a["uri"], "name": a.get("name"), "sub": "Artist", "image": _img(a.get("images"), 120)})
    for a in ((res.get("albums") or {}).get("items") or [])[:per]:
        if a and a.get("uri"):
            out["albums"].append({"uri": a["uri"], "name": a.get("name"), "sub": _artists(a), "image": _img(a.get("images"), 120)})
    for p in ((res.get("playlists") or {}).get("items") or [])[:per]:
        if p and p.get("uri"):
            out["playlists"].append({"uri": p["uri"], "name": p.get("name"),
                                     "sub": ((p.get("owner") or {}).get("display_name") or "Playlist"),
                                     "image": _img(p.get("images"), 120)})
    return out


def _player_key(p):
    if not p:
        return None
    item = p.get("item") or {}
    return (item.get("uri"), p.get("is_playing"), (p.get("device") or {}).get("id"),
            (p.get("device") or {}).get("volume_percent"), p.get("shuffle_state"), int((p.get("progress_ms") or 0) / 10000))


MOOD_WORDS = ("playlist", "mix", "music", "songs", "vibes", "chill", "relax", "focus", "party", "dinner",
              "workout", "sleep", "jazz", "classical", "acoustic", "hits", "radio")


def pick_result(query, res):
    """Choose what to play from a search answer. Returns (kind, uri, label) or None."""
    q = query.strip().lower()

    def items(kind):
        return [x for x in ((res.get(kind) or {}).get("items") or []) if x]
    tracks, artists, albums, playlists = items("tracks"), items("artists"), items("albums"), items("playlists")
    if artists and artists[0].get("name", "").lower() == q:
        return "context", artists[0]["uri"], artists[0]["name"]
    if " by " in q and tracks:
        return "track", tracks[0]["uri"], tracks[0]["name"]
    if any(w in q.split() for w in MOOD_WORDS) and playlists:
        return "context", playlists[0]["uri"], playlists[0].get("name")
    if tracks and tracks[0].get("name", "").lower() == q:
        return "track", tracks[0]["uri"], tracks[0]["name"]
    if albums and albums[0].get("name", "").lower() == q:
        return "context", albums[0]["uri"], albums[0]["name"]
    if playlists and playlists[0].get("name", "").lower() == q:
        return "context", playlists[0]["uri"], playlists[0]["name"]
    if tracks:
        return "track", tracks[0]["uri"], tracks[0]["name"]
    if playlists:
        return "context", playlists[0]["uri"], playlists[0].get("name")
    if artists:
        return "context", artists[0]["uri"], artists[0]["name"]
    return None
