"""The hub: holds the device adapters, builds the state, runs actions, tells every screen."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import contract as C

from .errors import DeviceDown, HubError

log = logging.getLogger("hub")
actions_log = logging.getLogger("hub.actions")

THROTTLE = 0.25        # seconds between two state messages on the events socket
BACKSTOP = 30          # seconds: send the state even if nothing seemed to change
ACTION_TIMEOUT = 50    # seconds an action may take (a TV waking takes up to 32)

DEVICE_OF = {"aircon": "aircon", "music": "speakers", "speakers": "speakers", "tv": "tvs"}


class Hub:
    def __init__(self, cfg, aircon, speakers, tvs, spotify=None):
        self.cfg = cfg
        self.aircon, self.speakers, self.tvs, self.spotify = aircon, speakers, tvs, spotify
        self.sockets = set()
        self._dirty = False
        self._flush_handle = None
        self._last_sent = None
        self._last_flush = 0.0
        self._task = None
        self.loop = None

    # ---------- life ----------
    async def start(self):
        self.loop = asyncio.get_running_loop()
        for name, dev in (("aircon", self.aircon), ("speakers", self.speakers), ("tvs", self.tvs),
                          ("spotify", self.spotify)):
            if dev is None:
                continue
            try:
                await dev.start()
            except Exception:
                log.exception("%s did not start", name)
        self._task = asyncio.create_task(self._backstop(), name="backstop")

    async def stop(self):
        log.info("hub stopping")
        if self._task:
            self._task.cancel()
        for ws in list(self.sockets):
            try:
                await ws.close()
            except Exception:
                pass
        for dev in (self.spotify, self.tvs, self.speakers, self.aircon):
            if dev is None:
                continue
            try:
                await asyncio.wait_for(dev.stop(), 10)
            except Exception:
                pass
        log.info("hub stopped")

    # ---------- state ----------
    def state(self):
        def part(dev, name, empty):
            try:
                return dev.snapshot()
            except Exception:
                log.exception("%s snapshot failed", name)
                return empty
        return {
            "version": C.API_VERSION,
            "updated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "aircon": part(self.aircon, "aircon", {"available": False, "power": False, "mode": None, "set": None,
                                                   "fan": None, "fan_speeds": [], "inside": None, "zones": []}),
            "speakers": part(self.speakers, "speakers", {"available": False, "devices": [], "groups": [],
                                                         "now": None, "spotify": {"linked": False}}),
            "tvs": part(self.tvs, "tvs", {"available": False, "devices": [], "apps": []}),
        }

    def changed(self):
        """Called by the adapters (on the event loop) or from threads through changed_threadsafe."""
        self._dirty = True
        if self._flush_handle is None and self.loop is not None:
            wait = max(0.0, THROTTLE - (time.monotonic() - self._last_flush))
            self._flush_handle = self.loop.call_later(wait, lambda: asyncio.ensure_future(self._flush()))

    def changed_threadsafe(self):
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.changed)

    async def _flush(self, force=False):
        self._flush_handle = None
        self._dirty = False
        self._last_flush = time.monotonic()
        st = self.state()
        key = json.dumps({k: v for k, v in st.items() if k != "updated"}, sort_keys=True, default=str)
        if not force and key == self._last_sent:
            return
        self._last_sent = key
        await self.broadcast(st)

    async def broadcast(self, st=None):
        if not self.sockets:
            return
        msg = json.dumps({"type": "state", "state": st or self.state()}, default=str)
        for ws in list(self.sockets):
            try:
                await ws.send_str(msg)
            except Exception:
                self.sockets.discard(ws)

    async def _backstop(self):
        while True:
            await asyncio.sleep(BACKSTOP)
            try:
                await self._flush(force=True)
            except Exception:
                log.exception("backstop flush failed")

    # ---------- actions ----------
    async def run(self, action, args, who="?"):
        """Validate and run one action. Returns the state. Raises HubError (plain words)."""
        try:
            name, clean = C.validate(action, args)
        except C.ContractError as e:
            actions_log.info("action %s by %s -> 400 %s", action if isinstance(action, str) else "?", who, e)
            raise HubError(400, str(e)) from None
        dev = DEVICE_OF[name.split(".")[0]]
        adapter = {"aircon": self.aircon, "speakers": self.speakers, "tvs": self.tvs}[dev]
        started = time.monotonic()
        try:
            await asyncio.wait_for(adapter.do(name, clean), ACTION_TIMEOUT)
        except HubError as e:
            actions_log.info("action %s %s by %s -> %s %s (%.1fs)", name, json.dumps(clean), who, e.status, e.text,
                             time.monotonic() - started)
            raise
        except asyncio.TimeoutError:
            actions_log.warning("action %s by %s -> timed out", name, who)
            raise DeviceDown(dev, "That took too long. Try again.") from None
        except Exception:
            log.exception("action %s failed", name)
            actions_log.warning("action %s %s by %s -> 503 (error)", name, json.dumps(clean), who)
            raise DeviceDown(dev) from None
        actions_log.info("action %s %s by %s -> ok (%.1fs)", name, json.dumps(clean), who, time.monotonic() - started)
        self.changed()
        return self.state()

    async def run_for_ask(self, action, args, source="ask"):
        """The Ask module's door: the same validate() and device path as POST /api/action."""
        try:
            await self.run(action, args, who=source if " via ask" in source else f"ask:{source}")
            return {"ok": True}
        except HubError as e:
            out = {"ok": False, "error": e.text}
            out.update({k: v for k, v in e.extra.items() if k in ("needs", "device")})
            return out
