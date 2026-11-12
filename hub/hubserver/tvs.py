"""The 3 TVs, through the couch-tv bridge (http://127.0.0.1:5400). The hub never changes the bridge.

Live: one /api/events stream per TV (server-sent events, the same JSON as /api/now).
Backstop: /api/tvs every 15 s (it also carries the Frame's Art Mode) and /api/now every 60 s.
If the hub config has bridge_key, every call sends it as X-Bridge-Key and X-API-Key (couch-tv's pairing_key).
"tvs" in the hub config lists the contract TVs this house has; the others are not shown or read.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import aiohttp

import contract as C

from .errors import Conflict, DeviceDown, TvOff

log = logging.getLogger("hub.tvs")

SKIP_APPS = {"settings", "home"}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


class Tvs:
    def __init__(self, cfg, on_change=lambda: None, session=None):
        self.base = cfg["bridge_url"].rstrip("/")
        self.key = cfg.get("bridge_key")
        self.names = cfg["tv_names"]
        # The contract's TVs this house has ("tvs" in config.json, default all). Only these are shown and read.
        want = cfg.get("tvs")
        self.present = [t for t in C.TVS if t in want] if isinstance(want, list) and want else list(C.TVS)
        self.on_change = on_change
        self.session = session
        self._own_session = session is None
        self.tvs = {}            # id -> row from /api/tvs
        self.now = {}            # id -> /api/now payload
        self.apps = {}           # id -> [app rows]
        self.apps_at = 0.0
        self.ok = False          # the bridge answered the last read
        self.ok_at = 0.0
        self._tasks = []

    def _headers(self):
        # couch-tv reads its pairing_key from X-API-Key (or Authorization: Bearer); X-Bridge-Key is kept for
        # bridges that read that one.
        return {"X-Bridge-Key": self.key, "X-API-Key": self.key} if self.key else {}

    # ---------- life ----------
    async def start(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        self._tasks = [asyncio.create_task(self._poll(), name="tvs-poll")]
        self._tasks += [asyncio.create_task(self._events(t), name=f"tvs-events-{t}") for t in self.present]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if self._own_session and self.session:
            await self.session.close()

    # ---------- bridge calls ----------
    async def _get(self, path, timeout=6, **params):
        try:
            async with self.session.get(self.base + path, params=params or None, headers=self._headers(),
                                        timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                body = await r.json(content_type=None)
                return r.status, body if isinstance(body, dict) else {}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            self._set_ok(False)
            raise DeviceDown("tvs") from e

    async def _post(self, path, data, timeout=10):
        try:
            async with self.session.post(self.base + path, json=data, headers=self._headers(),
                                         timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                try:
                    body = await r.json(content_type=None)
                except ValueError:
                    body = {}
                return r.status, body if isinstance(body, dict) else {}
        except asyncio.TimeoutError as e:
            raise DeviceDown("tvs", "The TV took too long to answer. Try again.") from e
        except aiohttp.ClientError as e:
            self._set_ok(False)
            raise DeviceDown("tvs") from e

    def _set_ok(self, ok):
        if ok:
            self.ok_at = time.time()
        if ok != self.ok:
            self.ok = ok
            self.on_change()

    async def read_all(self):
        st, body = await self._get("/api/tvs")
        if st == 401 or st == 403:
            self._set_ok(False)
            log.warning("tvs: the bridge wants a key (set bridge_key in config.json)")
            return
        rows = {t["id"]: t for t in body.get("tvs") or [] if isinstance(t, dict) and t.get("id")}
        changed = rows != self.tvs
        self.tvs = rows
        self._set_ok(True)
        if changed:
            self.on_change()

    async def read_now(self, tv):
        st, body = await self._get("/api/now", tv=tv)
        if st == 200 and body.get("ok"):
            self._set_now(tv, body)

    def _set_now(self, tv, body):
        body = {k: v for k, v in body.items() if k not in ("keyboard",)}
        pl = body.get("playing")
        if isinstance(pl, dict):    # the position moves every few seconds; it is not part of the hub state
            body["playing"] = {k: pl.get(k) for k in ("title", "state")}
        if body != self.now.get(tv):
            self.now[tv] = body
            self.on_change()

    async def read_apps(self):
        for tv in self.present:
            try:
                st, body = await self._get("/api/apps", tv=tv)
                if st == 200:
                    self.apps[tv] = [a for a in body.get("apps") or [] if isinstance(a, dict)]
            except DeviceDown:
                pass
        self.apps_at = time.time()
        self.on_change()

    async def _poll(self):
        n = 0
        while True:
            try:
                await self.read_all()
                if n % 4 == 0:
                    for tv in self.present:
                        await self.read_now(tv)
                if time.time() - self.apps_at > 600:
                    await self.read_apps()
            except asyncio.CancelledError:
                raise
            except DeviceDown:
                pass
            except Exception as e:
                log.info("tvs: poll failed: %s", type(e).__name__)
            n += 1
            await asyncio.sleep(15)

    async def _events(self, tv):
        backoff = 2
        while True:
            try:
                async with self.session.get(self.base + "/api/events", params={"tv": tv}, headers=self._headers(),
                                            timeout=aiohttp.ClientTimeout(total=None, sock_read=60)) as r:
                    if r.status != 200:
                        raise aiohttp.ClientResponseError(r.request_info, (), status=r.status)
                    backoff = 2
                    data = []
                    async for raw in r.content:
                        line = raw.decode("utf-8", "replace").rstrip("\r\n")
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                        elif line == "" and data:
                            try:
                                body = json.loads("\n".join(data))
                                if isinstance(body, dict):
                                    self._set_now(tv, body)
                                    self._set_ok(True)
                            except ValueError:
                                pass
                            data = []
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("tvs: events for %s ended: %s", tv, type(e).__name__)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    # ---------- state ----------
    def _row(self, tv):
        t = self.tvs.get(tv) or {}
        n = self.now.get(tv) or {}
        kind = t.get("kind") or ("samsung" if tv == "frame" else "android")
        power = n.get("power") or t.get("power")
        connected = n.get("tv_connected", t.get("connected"))
        on = power == "on" and connected is not False
        vol = n.get("volume") or {}
        app = n.get("app") or {}
        art = t.get("art_mode") if kind == "samsung" else None
        return {"id": tv, "name": self.names.get(tv, tv), "kind": kind, "power": "on" if on else "off",
                "app": (app.get("name") or None) if on else None,
                "volume": vol.get("level") if on and vol.get("known") else None,
                "muted": bool(vol.get("muted")) if on and vol else None,
                "art_mode": art if kind == "samsung" else None,
                "waking": bool(n.get("waking"))}

    def app_names(self):
        seen, out = set(), []
        for tv in self.present:
            for a in self.apps.get(tv, []):
                if a.get("installed") is False or (a.get("id") or "") in SKIP_APPS or not a.get("name"):
                    continue
                if _norm(a["name"]) not in seen:
                    seen.add(_norm(a["name"]))
                    out.append(a["name"])
        return out

    @property
    def available(self):
        return self.ok and bool(self.tvs)

    def snapshot(self):
        return {"available": self.available, "devices": [self._row(tv) for tv in self.present], "apps": self.app_names()}

    # ---------- doing ----------
    def _need(self, tv):
        if tv not in self.present:
            raise Conflict(f"{self.names.get(tv, tv)} is not one of this house's TVs.")
        if not self.available:
            raise DeviceDown("tvs")
        t = self.tvs.get(tv)
        if not t:
            raise DeviceDown("tvs", f"The bridge does not know the {self.names.get(tv, tv)} TV.")
        if t.get("paired") is False:
            raise DeviceDown("tvs", f"The {self.names.get(tv, tv)} TV is not paired with the bridge yet.")

    def _need_on(self, tv):
        self._need(tv)
        if self._row(tv)["power"] != "on":
            raise TvOff(self.names.get(tv, tv))

    async def _check(self, st, body, tv, timeout_text=None):
        if 200 <= st < 300 and body.get("ok", True):
            return body
        name = self.names.get(tv, tv)
        err = body.get("error") or ""
        if st in (401, 403):
            raise DeviceDown("tvs", "The TV bridge wants a key. Put bridge_key in the hub's config.json.")
        if st == 503:
            raise DeviceDown("tvs", timeout_text or f"The {name} TV is not answering.")
        if st == 404:
            raise Conflict(f"The {name} TV could not find that." + (f" ({err})" if err else ""))
        if st in (400, 409):
            raise Conflict(f"The {name} TV could not do that" + (f": {err}." if err else "."))
        raise DeviceDown("tvs", f"The {name} TV did not take the change.")

    async def _after(self, tv):
        try:
            await self.read_now(tv)
            await self.read_all()
        except DeviceDown:
            pass

    async def do(self, action, a):
        tv = a["tv"]
        name = self.names.get(tv, tv)
        if action == "tv.power":
            self._need(tv)
            st, body = await self._post("/api/power", {"tv": tv, "state": "on" if a["on"] else "off"}, timeout=45)
            await self._check(st, body, tv, timeout_text=(f"The {name} TV did not wake. Turn it on with its own remote."
                                                          if a["on"] else None))
        elif action == "tv.volume":
            self._need_on(tv)
            st, body = await self._post("/api/volume", {"tv": tv, "action": "up" if a["delta"] > 0 else "down",
                                                         "steps": abs(a["delta"])})
            if a["delta"] != 0:
                await self._check(st, body, tv)
        elif action == "tv.mute":
            self._need_on(tv)
            cur = self._row(tv)["muted"]
            if cur is not a["muted"]:
                st, body = await self._post("/api/volume", {"tv": tv, "action": "mute"})
                await self._check(st, body, tv)
        elif action == "tv.launch":
            self._need_on(tv)
            if time.time() - self.apps_at > 600 or not self.apps.get(tv):
                await self.read_apps()
            want = _norm(a["app"])
            match = next((x for x in self.apps.get(tv, []) if want in (_norm(x.get("name")), _norm(x.get("id")))), None)
            if match is None:
                match = next((x for x in self.apps.get(tv, []) if want and want in _norm(x.get("name"))), None)
            if match is None or match.get("installed") is False:
                raise Conflict(f"The {name} TV has no app called {a['app']}.")
            st, body = await self._post("/api/launch", {"tv": tv, "app": match.get("id") or match.get("package")})
            await self._check(st, body, tv)
        elif action == "tv.play":
            self._need_on(tv)
            st, body = await self._post("/api/play", {"tv": tv, "title": a["title"]}, timeout=40)
            if st == 404:
                raise Conflict(f"Couldn't find {a['title']} to play.")
            await self._check(st, body, tv)
        elif action == "tv.art_mode":
            self._need(tv)
            row = self._row(tv)
            if row["art_mode"] is a["on"]:
                return
            if a["on"]:
                if row["power"] != "on":
                    raise TvOff(name)
                # On a Frame, one press of power while watching goes to Art Mode.
                st, body = await self._post("/api/key", {"tv": tv, "key": "power"})
            else:
                st, body = await self._post("/api/power", {"tv": tv, "state": "on"}, timeout=45)
            await self._check(st, body, tv)
            for _ in range(12):
                await asyncio.sleep(0.5)
                await self._after(tv)
                if self._row(tv)["art_mode"] is a["on"]:
                    break
            return
        await self._after(tv)
