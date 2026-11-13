"""WiZ lights, spoken to directly on the home network (UDP 38899, JSON). No cloud and no account.

"lights" in the hub's config.json lists them, in the order the wall shows them:

    "lights": [{"id": "lamp", "name": "Lamp", "mac": "a8bb50aabbcc", "ip": "192.0.2.50"},
               {"id": "bedroom", "name": "Bedroom", "bulbs": [{"mac": "...", "ip": "..."}, {"mac": "...", "ip": "..."}]}]

A light with "bulbs" is a room or a fitting of several bulbs: the wall shows one light and every change goes to
all of them.

"mac" is what names a bulb for good; "ip" is where it was last seen. A bulb that stops answering there is looked
for across that /24 (one small question to each address) and found again by its mac, so a new address from the
router needs no change here.

Each bulb is asked for its state (getPilot) every few seconds and changed with setPilot. A bulb that is switched
off at the wall does not answer: it shows as not available.

Schedules: each light can have a few (lights.schedule / lights.unschedule), kept in ~/.home-hub/light-schedules.json.
The hub runs them, by this computer's clock, so they only happen while the hub is running. At its time on its
days a schedule turns the light on or off; with a fade it starts dim and warm and climbs to its brightness over
that many minutes (or dims down and then turns off). A change made by hand during a fade stops the fade.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import socket
import sys
import time
from datetime import datetime

import contract as C

from . import config as cfgmod
from .errors import Conflict, DeviceDown

log = logging.getLogger("hub.lights")

PORT = 38899
POLL = 4            # seconds between two reads of a bulb
GONE = 14           # seconds without an answer before a bulb counts as not available
SWEEP_EVERY = 60    # seconds between two searches for bulbs that are not answering
SCHEDULE_FILE = "light-schedules.json"
TICK = 15           # seconds between two looks at the schedules
LATE = 120          # seconds after its time a schedule may still start (the hub was busy or just started)
FADE_STEP = 20      # seconds between two steps of a fade, at most


def _hex(r, g, b):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(x or 0))) for x in (r, g, b))


def signed(method, params, key, now=None):
    """A request the way newer WiZ firmware (1.34 and later) wants a change: sigTs (unix seconds) added to params,
    "env": "pro", and an HMAC-SHA256 of the compact params JSON, keyed with the home's signing key, in base64.
    (The scheme pywizlight uses; an unsigned change gets -32602 Invalid params, a wrong signature -32605.)"""
    params = dict(params or {})
    params["sigTs"] = int(time.time() if now is None else now)
    digest = hmac.new(key, json.dumps(params, separators=(",", ":")).encode("utf-8"), hashlib.sha256).digest()
    return {"method": method, "env": "pro", "params": params, "hmac": base64.b64encode(digest).decode("ascii")}


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, owner):
        self.owner = owner

    def datagram_received(self, data, addr):
        try:
            msg = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            return
        if isinstance(msg, dict):
            self.owner._received(msg, addr[0])

    def error_received(self, exc):      # an address with nothing on it (Windows reports it): not an error here
        pass


class Lights:
    def __init__(self, cfg, on_change=lambda: None, port=PORT, schedule_file=None):
        self.on_change = on_change
        self.port = port
        self.minute = 60.0       # seconds in a fade minute (tests make it short)
        self.bulbs = []          # config order: {"id", "name", "mac", "ip", "seen", "pilot"}
        for row in cfg.get("lights") or []:
            if not isinstance(row, dict):
                continue
            lid, mac = str(row.get("id") or "").strip(), re.sub(r"[^0-9a-f]", "", str(row.get("mac") or "").lower())
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", lid) or lid == C.LIGHT_ALL or any(b["id"] == lid for b in self.bulbs):
                log.warning("lights: skipped a light in config.json (its id must be short, lower case and its own)")
                continue
            # One light can be several bulbs ("bulbs": a room or a fitting): they are shown and changed as one.
            parts = row.get("bulbs") if isinstance(row.get("bulbs"), list) else [row]
            for part in parts:
                if not isinstance(part, dict):
                    continue
                mac = re.sub(r"[^0-9a-f]", "", str(part.get("mac") or "").lower())
                self.bulbs.append({"id": lid, "name": str(row.get("name") or lid), "mac": mac,
                                   "ip": str(part.get("ip") or "").strip() or None, "seen": 0.0, "pilot": {}})
        # "lights_key": the WiZ home's udp_signing_key (32 hex characters, from the WiZ app's local integration
        # export). Newer bulb firmware only takes signed changes unless the app allows all local controls.
        self.key = None
        raw = re.sub(r"\s", "", str(cfg.get("lights_key") or ""))
        if raw:
            try:
                self.key = bytes.fromhex(raw)
            except ValueError:
                log.warning("lights: lights_key in config.json is not hex, so changes are sent unsigned")
        self._transport = None
        self._waiting = {}      # (ip, method) -> future, for the answer to a setPilot
        self._tasks = []
        self._swept = 0.0
        self._schedule_file = schedule_file or cfgmod.path(SCHEDULE_FILE)
        self.schedules = {}     # light id -> [schedule], in time order
        self._fired = {}        # schedule id -> the start it last ran for (so it runs once)
        self._fades = {}        # light id -> the task running its scheduled change
        self._load_schedules()

    # ---------- life ----------
    async def start(self):
        if not self.bulbs:
            return
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.bind(("0.0.0.0", 0))
        if sys.platform == "win32":
            # Windows turns "nothing listens at that address" into an error on the next read, and asyncio's
            # reader then stops for good: every later answer would be lost. Ask Windows not to report it.
            # (SIO_UDP_CONNRESET off; Python's own socket.ioctl does not know this one, so WSAIoctl is called.)
            try:
                import ctypes
                from ctypes import wintypes
                flag, done = wintypes.BOOL(False), wintypes.DWORD(0)
                rc = ctypes.windll.ws2_32.WSAIoctl(ctypes.c_size_t(sock.fileno()), wintypes.DWORD(0x9800000C),
                                                   ctypes.byref(flag), ctypes.sizeof(flag), None, 0,
                                                   ctypes.byref(done), None, None)
                if rc != 0:
                    raise OSError("WSAIoctl failed")
            except Exception:
                log.warning("lights: could not turn off UDP reset reports")
        self._transport, _ = await loop.create_datagram_endpoint(lambda: _Proto(self), sock=sock)
        self._tasks = [asyncio.create_task(self._poll(), name="lights-poll"),
                       asyncio.create_task(self._scheduler(), name="lights-schedules")]

    async def stop(self):
        for t in list(self._fades.values()):
            t.cancel()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if self._transport:
            self._transport.close()

    # ---------- the wire ----------
    def _send(self, ip, method, params=None):
        if self._transport is None or not ip:
            return
        msg = {"method": method, "params": params or {}}
        if self.key and method != "getPilot":
            msg = signed(method, params, self.key)
        try:
            self._transport.sendto(json.dumps(msg, separators=(",", ":")).encode(), (ip, self.port))
        except OSError:
            pass

    def _received(self, msg, ip):
        method = msg.get("method")
        res = msg.get("result")
        if not isinstance(res, dict):
            err = msg.get("error")
            fut = self._waiting.pop((ip, method), None) if isinstance(err, dict) else None
            if fut is not None and not fut.done():
                fut.set_result({"success": False, "code": err.get("code")})   # refused: asking again changes nothing
            return
        if method == "getPilot":
            mac = re.sub(r"[^0-9a-f]", "", str(res.get("mac") or "").lower())
            bulb = next((b for b in self.bulbs if b["mac"] and b["mac"] == mac), None) \
                or next((b for b in self.bulbs if not b["mac"] and b["ip"] == ip), None)
            if bulb is None:
                return
            was = self._row(bulb)
            if bulb["ip"] != ip:
                log.info("lights: %s is now at a new address", bulb["id"])
                bulb["ip"] = ip
            bulb["seen"], bulb["pilot"] = time.time(), res
            if self._row(bulb) != was:
                self.on_change()
        fut = self._waiting.pop((ip, method), None)
        if fut is not None and not fut.done():
            fut.set_result(res)

    async def _ask(self, ip, method, params, timeout=1.2, tries=3):
        """Send and wait for the bulb's own answer (UDP: asked again when nothing comes back)."""
        loop = asyncio.get_running_loop()
        for _ in range(tries):
            fut = loop.create_future()
            self._waiting[(ip, method)] = fut
            self._send(ip, method, params)
            try:
                return await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                self._waiting.pop((ip, method), None)
        return None

    async def _poll(self):
        while True:
            try:
                now = time.time()
                for b in self.bulbs:
                    self._send(b["ip"], "getPilot")
                lost = [b for b in self.bulbs if now - b["seen"] > GONE]
                if lost and now - self._swept > SWEEP_EVERY:
                    self._swept = now
                    await self._sweep(lost)
                for b in lost:               # a bulb that has just gone quiet: the wall should say so
                    if b["pilot"]:
                        b["pilot"] = {}
                        self.on_change()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.info("lights: poll failed: %s", type(e).__name__)
            await asyncio.sleep(POLL)

    async def _sweep(self, lost):
        """Ask every address of the /24 a lost bulb was on; the answers carry the mac (see _received)."""
        nets = {b["ip"].rsplit(".", 1)[0] for b in lost if b["ip"] and b["mac"] and re.fullmatch(r"(\d+\.){3}\d+", b["ip"])}
        for net in nets:
            for i in range(1, 255):
                self._send(f"{net}.{i}", "getPilot")
                if i % 32 == 0:
                    await asyncio.sleep(0.05)

    # ---------- state ----------
    def _row(self, b):
        p = b["pilot"] or {}
        up = bool(p) and time.time() - b["seen"] <= GONE
        white = up and p.get("temp") is not None
        colour = up and not white and any(k in p for k in ("r", "g", "b"))
        return {"id": b["id"], "name": b["name"], "available": up,
                "on": bool(p.get("state")) if up else False,
                "brightness": p.get("dimming") if up else None,
                "kelvin": p.get("temp") if white else None,
                "color": _hex(p.get("r"), p.get("g"), p.get("b")) if colour else None}

    def snapshot(self):
        rows = {}
        for b in self.bulbs:        # the bulbs of one light as one row: on when any is on, the look of the first lit
            r = self._row(b)
            have = rows.get(b["id"])
            if have is None:
                rows[b["id"]] = r
            elif r["available"] and (not have["available"] or (r["on"] and not have["on"])):
                rows[b["id"]] = r
        rows = list(rows.values())
        for r in rows:
            r["schedules"] = [dict(s) for s in self.schedules.get(r["id"], [])]
            r["fading"] = r["id"] in self._fades
        return {"available": any(r["available"] for r in rows), "devices": rows}

    # ---------- schedules ----------
    def _load_schedules(self):
        data = cfgmod.read_json(self._schedule_file, {}) or {}
        ids = {b["id"] for b in self.bulbs}
        for lid, rows in (data.items() if isinstance(data, dict) else []):
            if lid not in ids or not isinstance(rows, list):
                continue
            keep = []
            for s in rows:
                try:            # a hand-edited file is checked the same way an action is
                    _, a = C.validate("lights.schedule", {k: v for k, v in s.items() if k != "id" and v is not None}
                                      | {"light": lid})
                    a["id"] = C.ACTIONS["lights.unschedule"][1]["schedule"](s.get("id"))
                    keep.append(self._clean(a))
                except (C.ContractError, AttributeError, TypeError):
                    log.warning("lights: skipped a schedule in %s", SCHEDULE_FILE)
            self.schedules[lid] = sorted(keep, key=lambda s: s["time"])[:C.SCHEDULES_MAX]

    def _save_schedules(self):
        cfgmod.write_json(self._schedule_file, {k: v for k, v in self.schedules.items() if v})

    @staticmethod
    def _clean(a, old=None):
        s = dict(old or {})
        for k in ("id", "time", "days", "do", "brightness", "kelvin", "fade", "enabled"):
            if k in a:
                s[k] = a[k]
        s.setdefault("fade", 0)
        s.setdefault("enabled", True)
        if s["do"] == "on":
            s["brightness"] = s.get("brightness") or 100
            s["kelvin"] = s.get("kelvin") or 2700
        else:
            s["brightness"] = s["kelvin"] = None
        return {k: s[k] for k in ("id", "time", "days", "do", "brightness", "kelvin", "fade", "enabled")}

    def _schedule(self, action, a):
        lid = a["light"]
        if lid == C.LIGHT_ALL:
            raise Conflict("Pick one light for a schedule.")
        if not any(b["id"] == lid for b in self.bulbs):
            raise Conflict("That is not one of this house's lights.")
        rows = self.schedules.setdefault(lid, [])
        sid = a.get("schedule")
        old = next((s for s in rows if s["id"] == sid), None) if sid else None
        if sid and old is None:
            raise Conflict("That schedule is not there any more.")
        if action == "lights.unschedule":
            rows.remove(old)
        elif old is not None:
            rows[rows.index(old)] = self._clean(a, old)
        else:
            if len(rows) >= C.SCHEDULES_MAX:
                raise Conflict(f"A light can have {C.SCHEDULES_MAX} schedules. Remove one first.")
            rows.append(self._clean({**a, "id": secrets.token_hex(3)}))
        rows.sort(key=lambda s: s["time"])
        if sid:
            self._fired.pop(sid, None)
        self._save_schedules()
        self.on_change()

    async def _scheduler(self):
        while True:
            try:
                self.run_due(datetime.now().astimezone())
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("lights: schedules")
            await asyncio.sleep(TICK)

    def run_due(self, now):
        """Start every schedule whose time has just come (within LATE seconds), once per day."""
        day = C.DAYS[now.weekday()]
        for lid, rows in self.schedules.items():
            for s in rows:
                if not s["enabled"] or day not in s["days"]:
                    continue
                start = now.replace(hour=int(s["time"][:2]), minute=int(s["time"][3:]), second=0, microsecond=0)
                late = (now - start).total_seconds()
                if 0 <= late < LATE and self._fired.get(s["id"]) != start.isoformat():
                    self._fired[s["id"]] = start.isoformat()
                    log.info("lights: schedule %s %s at %s", lid, s["do"], s["time"])
                    self._stop_fade(lid)
                    self._fades[lid] = asyncio.create_task(self._run(lid, s), name=f"lights-run-{lid}")
                    self.on_change()

    def _stop_fade(self, lid):
        for k in ([lid] if lid != C.LIGHT_ALL else list(self._fades)):
            t = self._fades.pop(k, None)
            if t is not None and t is not asyncio.current_task():
                t.cancel()
                self.on_change()

    async def _run(self, lid, s):
        try:
            mine = lambda: [b for b in self.bulbs if b["id"] == lid and self._row(b)["available"]]  # noqa: E731
            fade = s["fade"]
            if s["do"] == "on":
                b1, k1 = s["brightness"], s["kelvin"]
                was_on = any(self._row(b)["on"] for b in mine())
                if fade <= 0 or was_on:     # already on: go straight to the look, no dip to dim first
                    await self._apply(mine(), {"state": True, "dimming": b1, "temp": k1})
                    return
                b0, k0 = C.LIGHT_BRIGHT_MIN, min(C.LIGHT_TEMP_MIN, k1)
            else:
                rows = [self._row(b) for b in mine()]
                if fade <= 0 or not any(r["on"] for r in rows):
                    await self._apply(mine(), {"state": False})
                    return
                b0 = max([r["brightness"] or 0 for r in rows if r["on"]] or [100])
                b1, k0, k1 = C.LIGHT_BRIGHT_MIN, None, None
            total = fade * self.minute
            steps = max(1, min(int(total // min(FADE_STEP, self.minute / 3)) or 1, abs(b1 - b0) or 1))
            last = None
            for i in range(steps + 1):
                f = i / steps
                p = {"state": True, "dimming": round(b0 + (b1 - b0) * f)}
                if k0 is not None:
                    p["temp"] = int(round((k0 + (k1 - k0) * f) / 100) * 100)
                if p != last:
                    await self._apply(mine(), p)
                    last = p
                if i < steps:
                    await asyncio.sleep(total / steps)
            if s["do"] == "off":
                await self._apply(mine(), {"state": False})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.info("lights: schedule for %s stopped: %s", lid, type(e).__name__)
        finally:
            if self._fades.get(lid) is asyncio.current_task():
                self._fades.pop(lid, None)
                self.on_change()

    # ---------- doing ----------
    def _targets(self, light):
        if light == C.LIGHT_ALL:
            if not self.bulbs:
                raise Conflict("This house has no lights set up.")
            up = [b for b in self.bulbs if self._row(b)["available"]]
            if not up:
                raise DeviceDown("lights")
            return up
        mine = [b for b in self.bulbs if b["id"] == light]
        if not mine:
            raise Conflict("That is not one of this house's lights.")
        up = [b for b in mine if self._row(b)["available"]]
        if not up:
            raise DeviceDown("lights", f"The {mine[0]['name']} light is not answering. Check it is switched on at the wall.")
        return up

    async def do(self, action, a):
        if action in ("lights.schedule", "lights.unschedule"):
            self._schedule(action, a)
            return
        bulbs = self._targets(a["light"])
        self._stop_fade(a["light"])     # a change by hand wins over a scheduled fade
        if action == "lights.power":
            params = {"state": a["on"]}
        elif action == "lights.brightness":
            params = {"state": True, "dimming": a["value"]}
        elif action == "lights.white":
            params = {"state": True, "temp": a["kelvin"]}
        elif action == "lights.color":
            c = a["color"]
            params = {"state": True, "r": int(c[1:3], 16), "g": int(c[3:5], 16), "b": int(c[5:7], 16)}
        else:
            raise Conflict("That is not something the lights can do.")
        await self._apply(bulbs, params)

    async def _apply(self, bulbs, params):
        """Send one change to some bulbs and show it at once. Raises in plain words when one did not take it."""
        if not bulbs:
            raise DeviceDown("lights")
        answers = await asyncio.gather(*(self._ask(b["ip"], "setPilot", params) for b in bulbs))
        failed = [b for b, r in zip(bulbs, answers) if not (r and r.get("success"))]
        for b, r in zip(bulbs, answers):
            if r and r.get("success"):      # show it at once; the next read confirms it
                p = dict(b["pilot"])
                p.update(params)
                if "temp" in params:
                    for k in ("r", "g", "b", "c", "w"):
                        p.pop(k, None)
                if "r" in params:
                    p.pop("temp", None)
                b["pilot"], b["seen"] = p, time.time()
                self._send(b["ip"], "getPilot")
        if failed:
            codes = {(r or {}).get("code") for r in answers}
            if codes & {-32602, -32605}:        # newer firmware: it wants a signed change, or the key is wrong
                raise Conflict("The lights only take changes from a verified app. In the WiZ app: Settings, Security, "
                               "Allow local communication, Allow all controls. Or put the home's signing key in "
                               "lights_key." if not self.key else
                               "The lights refused the signing key. Check lights_key in the hub's config.json.")
            raise DeviceDown("lights", f"The {failed[0]['name']} light did not take the change.")
