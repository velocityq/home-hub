"""The aircon: a Daikin on an AirTouch 5 console, spoken to directly over TCP port 9005.

One connection stays open (airtouch5py's Airtouch5SimpleClient). The console pushes a status
packet whenever something changes, so the state is live. If the connection stays down, the hub
runs the AirTouch discovery broadcast (the console has moved address before, .41 to .39) and
remembers where it found it.
"""
from __future__ import annotations

import asyncio
import logging
import time

import contract as C

from .errors import DeviceDown

log = logging.getLogger("hub.aircon")

DOWN_LIMIT = 20          # seconds the connection may be down before the hub looks for the console
POLL_EVERY = 60          # backstop: ask for the status this often
CONFIRM_TIMEOUT = 5      # seconds to wait for the console to confirm a change


def _lib():
    """airtouch5py, imported late so tests can run without a console."""
    from airtouch5py.airtouch5_client import Airtouch5ConnectionStateChange
    from airtouch5py.packets import ac_control as acc
    from airtouch5py.packets import ac_status as acs
    from airtouch5py.packets import zone_control as zc
    from airtouch5py.packets import zone_status as zs
    return Airtouch5ConnectionStateChange, acc, acs, zc, zs


def _real_client(ip):
    from airtouch5py.airtouch5_simple_client import Airtouch5SimpleClient
    return Airtouch5SimpleClient(ip)


async def _real_discover():
    from airtouch5py.discovery import AirtouchDiscovery
    d = AirtouchDiscovery()
    try:
        await d.establish_server()
        found = await asyncio.wait_for(d.discover(), 8)
        return [x.ip for x in found if getattr(x, "ip", None)]
    finally:
        await d.close()


class Aircon:
    def __init__(self, cfg, on_change=lambda: None, client_factory=None, discover=None,
                 remember=None, recall=None):
        self.cfg = cfg
        self.on_change = on_change
        self.client_factory = client_factory or _real_client
        self.discover = discover or _real_discover
        self.remember = remember or (lambda k, v: None)
        last = (recall or (lambda k, d=None: d))("airtouch_ip")
        self.ip = last or cfg["airtouch_host"]
        self.zone_ids = cfg["zones"]                 # contract id -> console zone name
        self.inside_zone = cfg.get("inside_zone", "living")
        self.client = None
        self.ability = None
        self.zone_numbers: dict[str, int] = {}       # contract id -> console zone number
        self.zone_status: dict[int, object] = {}
        self.ac_status = None
        self.connected = False
        self.down_since = None
        self.last_packet = 0.0
        self.notes: list[str] = []                   # what was seen (for the report and /api/health logs)
        self._task = None
        self._stop = False
        self._event = asyncio.Event()
        self._lock = asyncio.Lock()

    # ---------- life ----------
    async def start(self):
        self._task = asyncio.create_task(self._run(), name="aircon")

    async def stop(self):
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self._close()

    @property
    def available(self):
        return self.connected and self.ac_status is not None

    def _note(self, text):
        log.warning("aircon: %s", text)
        self.notes = (self.notes + [f"{time.strftime('%H:%M:%S')} {text}"])[-20:]

    async def _run(self):
        backoff = 2
        while not self._stop:
            looked = False
            try:
                if not self.ip:
                    raise LookupError("no console address yet")
                await self._connect(self.ip)
                backoff = 2
                await self._watch()
                self._note(f"connection to {self.ip} down for over {DOWN_LIMIT}s")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                kind = type(e).__name__
                if isinstance(e, ConnectionRefusedError):
                    self._note(f"{self.ip} refused the connection (console busy or at its connection limit?)")
                elif isinstance(e, ConnectionResetError):
                    self._note(f"{self.ip} reset the connection (console at its connection limit?)")
                elif isinstance(e, LookupError):
                    log.info("aircon: no console address yet, looking for it")
                else:
                    self._note(f"could not connect to {self.ip}: {kind} {e}".strip())
            self._set_connected(False)
            await self._close()
            if self._stop:
                break
            try:
                ips = await self.discover()
            except Exception as e:
                ips = []
                log.info("aircon: discovery failed: %s", type(e).__name__)
            looked = True
            if ips and ips[0] != self.ip:
                self._note(f"found the console at {ips[0]} (was {self.ip})")
                self.ip = ips[0]
                self.remember("airtouch_ip", self.ip)
                continue
            if looked and not ips:
                log.info("aircon: discovery found no console")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _connect(self, ip):
        conn, *_ = _lib()
        c = self.client_factory(ip)
        self.client = c
        await asyncio.wait_for(c.connect_and_stay_connected(), 20)
        self.ability = next((a for a in c.ac if a.ac_number == 0), c.ac[0] if c.ac else None)
        names = {z.zone_name.strip().lower(): z.zone_number for z in c.zones}
        self.zone_numbers = {zid: names[n.lower()] for zid, n in self.zone_ids.items() if n.lower() in names}
        missing = [n for zid, n in self.zone_ids.items() if zid not in self.zone_numbers]
        if missing:
            self._note("zones not on the console: " + ", ".join(missing))
        self.zone_status = dict(c.latest_zone_status)
        self.ac_status = c.latest_ac_status.get(0) or next(iter(c.latest_ac_status.values()), None)
        c.zone_status_callbacks.append(self._on_zones)
        c.ac_status_callbacks.append(self._on_ac)
        c.connection_state_callbacks.append(self._on_conn)
        self.last_packet = time.time()
        self._set_connected(True)
        log.info("aircon: connected to %s (console %s, AC %s)", ip, getattr(c, "console_version", "?"),
                 getattr(self.ability, "ac_name", "?"))

    async def _watch(self):
        """Return when the connection has been down too long (or the client's task died)."""
        last_poll = time.time()
        while not self._stop:
            await asyncio.sleep(1)
            task = getattr(self.client, "_connection_task", None)
            if task is not None and task.done():
                return
            if self.down_since and time.time() - self.down_since > DOWN_LIMIT:
                return
            if self.connected and time.time() - last_poll > POLL_EVERY:
                last_poll = time.time()
                await self.refresh()

    async def refresh(self):
        """Ask the console for the zone and AC status (they arrive through the callbacks)."""
        c = self.client
        if not c or not self.connected:
            return
        try:
            await c.send_packet(c.data_packet_factory.zone_status_request())
            await c.send_packet(c.data_packet_factory.ac_status_request())
        except Exception as e:
            log.info("aircon: status request failed: %s", type(e).__name__)

    async def _close(self):
        c, self.client = self.client, None
        if c is None:
            return
        for lst, cb in ((getattr(c, "zone_status_callbacks", []), self._on_zones),
                        (getattr(c, "ac_status_callbacks", []), self._on_ac),
                        (getattr(c, "connection_state_callbacks", []), self._on_conn)):
            if cb in lst:
                lst.remove(cb)
        try:
            if getattr(c, "_connection_task", None) is None:
                await c._client.disconnect()   # the library's disconnect() needs the task to exist
            else:
                await asyncio.wait_for(c.disconnect(), 5)
        except Exception:
            pass

    # ---------- callbacks from airtouch5py (same event loop) ----------
    def _on_conn(self, change):
        conn, *_ = _lib()
        if change == conn.DISCONNECTED:
            self._note(f"lost the connection to {self.ip}")
            self._set_connected(False)
        elif change == conn.CONNECTED:
            log.info("aircon: connected again to %s", self.ip)
            self._set_connected(True)
            asyncio.get_running_loop().create_task(self.refresh())

    def _on_zones(self, zones):
        self.zone_status.update(zones)        # merge: a packet may carry only some zones
        self._packet()

    def _on_ac(self, acs):
        st = acs.get(0) or next(iter(acs.values()), None)
        if st is not None:
            self.ac_status = st
        self._packet()

    def _packet(self):
        self.last_packet = time.time()
        if not self.connected:
            self._set_connected(True)
        ev, self._event = self._event, asyncio.Event()
        ev.set()
        self.on_change()

    def _set_connected(self, on):
        if on:
            self.down_since = None
        elif self.connected or self.down_since is None:
            self.down_since = time.time()
        if on != self.connected:
            self.connected = on
            self.on_change()

    # ---------- state ----------
    def fan_speeds(self):
        a = self.ability
        if a is None:
            return []
        have = {
            "auto": a.supports_fan_speed_auto or a.supports_fan_speed_intelligent_auto,
            "quiet": a.supports_fan_speed_quiet, "low": a.supports_fan_speed_low,
            "medium": a.supports_fan_speed_medium, "high": a.supports_fan_speed_high,
            "powerful": a.supports_fan_speed_powerful, "turbo": a.supports_fan_speed_turbo,
        }
        return [f for f in C.FAN_SPEEDS if have.get(f)]

    def snapshot(self):
        _, acc, acs, zc, zs = _lib()
        st = self.ac_status
        zones = []
        for zid, zname in self.zone_ids.items():
            n = self.zone_numbers.get(zid)
            z = self.zone_status.get(n) if n is not None else None
            if z is None:
                zones.append({"id": zid, "name": zname, "on": False, "temp": None, "open": 0})
                continue
            on = z.zone_power_state in (zs.ZonePowerState.ON, zs.ZonePowerState.TURBO)
            t = z.temperature if isinstance(z.temperature, (int, float)) else None
            zones.append({"id": zid, "name": zname, "on": on, "temp": round(t, 1) if t is not None else None,
                          "open": int(round((z.open_percentage or 0) * 100))})
        inside = next((z["temp"] for z in zones if z["id"] == self.inside_zone), None)
        if st is None:
            return {"available": False, "power": False, "mode": None, "set": None, "fan": None,
                    "fan_speeds": self.fan_speeds(), "inside": inside, "zones": zones}
        power = st.ac_power_state in (acs.AcPowerState.ON, acs.AcPowerState.AWAY_ON, acs.AcPowerState.SLEEP)
        mode = {acs.AcMode.AUTO: "auto", acs.AcMode.AUTO_HEAT: "auto", acs.AcMode.AUTO_COOL: "auto",
                acs.AcMode.COOL: "cool", acs.AcMode.HEAT: "heat", acs.AcMode.DRY: "dry",
                acs.AcMode.FAN: "fan"}.get(st.ac_mode)
        fan = st.ac_fan_speed.name.lower()
        if fan.startswith("intelligent_auto"):
            fan = "auto"
        if fan not in C.FAN_SPEEDS:
            fan = None
        sp = st.ac_setpoint
        return {"available": self.available, "power": power, "mode": mode,
                "set": int(round(sp)) if isinstance(sp, (int, float)) else None, "fan": fan,
                "fan_speeds": self.fan_speeds(), "inside": inside, "zones": zones}

    # ---------- actions ----------
    def _need(self):
        if not self.available or self.client is None:
            raise DeviceDown("aircon")

    async def _send_and_confirm(self, packet, done):
        """Send one packet, then wait until the console's status says done() (or a packet came and time ran out)."""
        async with self._lock:
            self._need()
            got = False
            try:
                ev = self._event
                await self.client.send_packet(packet)
            except Exception as e:
                log.warning("aircon: send failed: %s", type(e).__name__)
                raise DeviceDown("aircon", "The aircon did not take the change. Try again.") from e
            end = time.monotonic() + CONFIRM_TIMEOUT
            while time.monotonic() < end:
                try:
                    await asyncio.wait_for(ev.wait(), max(0.05, end - time.monotonic()))
                except asyncio.TimeoutError:
                    break
                got = True
                if done():
                    return
                ev = self._event
            if not got:
                # no answer at all: ask for the status once more before giving up
                await self.refresh()
                await asyncio.sleep(1.0)
                if done():
                    return
                raise DeviceDown("aircon", "The aircon did not answer. Try again.")
            log.info("aircon: change sent, the console's status shows something else (it may have its own limits)")

    def _ac_packet(self, power=None, mode=None, fan=None, setpoint=None):
        _, acc, *_ = _lib()
        ctl = acc.AcControl(
            power or acc.SetPowerSetting.KEEP_POWER_SETTING,
            self.ability.ac_number if self.ability else 0,
            mode or acc.SetAcMode.KEEP_AC_MODE,
            fan or acc.SetAcFanSpeed.KEEP_AC_FAN_SPEED,
            acc.SetpointControl.CHANGE_SETPOINT if setpoint is not None else acc.SetpointControl.KEEP_SETPOINT_VALUE,
            int(setpoint) if setpoint is not None else 0,
        )
        return self.client.data_packet_factory.ac_control([ctl])

    def _limits(self):
        a = self.ability
        lo, hi = C.TEMP_MIN, C.TEMP_MAX
        if a is not None:
            lo = max(lo, min(a.min_cool_set_point, a.min_heat_set_point))
            hi = min(hi, max(a.max_cool_set_point, a.max_heat_set_point))
        return lo, hi

    async def do(self, action, a):
        self._need()
        _, acc, acs, zc, zs = _lib()
        snap = self.snapshot()
        if action == "aircon.power":
            want = a["on"]
            pkt = self._ac_packet(power=acc.SetPowerSetting.SET_TO_ON if want else acc.SetPowerSetting.SET_TO_OFF)
            await self._send_and_confirm(pkt, lambda: self.snapshot()["power"] == want)
        elif action in ("aircon.set_temp", "aircon.nudge"):
            lo, hi = self._limits()
            cur = snap["set"]
            if action == "aircon.nudge" and cur is None:
                raise DeviceDown("aircon", "The aircon has not said its temperature yet. Try again.")
            want = a["value"] if action == "aircon.set_temp" else cur + a["delta"]
            want = max(lo, min(hi, want))
            if want == cur:
                return
            await self._send_and_confirm(self._ac_packet(setpoint=want), lambda: self.snapshot()["set"] == want)
        elif action == "aircon.mode":
            m = {"auto": acc.SetAcMode.SET_TO_AUTO, "cool": acc.SetAcMode.SET_TO_COOL, "heat": acc.SetAcMode.SET_TO_HEAT,
                 "dry": acc.SetAcMode.SET_TO_DRY, "fan": acc.SetAcMode.SET_TO_FAN}[a["mode"]]
            want = a["mode"]
            pkt = self._ac_packet(power=acc.SetPowerSetting.SET_TO_ON, mode=m)
            await self._send_and_confirm(pkt, lambda: self.snapshot()["mode"] == want and self.snapshot()["power"])
        elif action == "aircon.fan":
            have = self.fan_speeds() or list(C.FAN_SPEEDS)
            want = a["speed"] if a["speed"] in have else min(
                have, key=lambda f: abs(C.FAN_SPEEDS.index(f) - C.FAN_SPEEDS.index(a["speed"])))
            f = {"auto": acc.SetAcFanSpeed.SET_TO_AUTO, "quiet": acc.SetAcFanSpeed.SET_TO_QUIET,
                 "low": acc.SetAcFanSpeed.SET_TO_LOW, "medium": acc.SetAcFanSpeed.SET_TO_MEDIUM,
                 "high": acc.SetAcFanSpeed.SET_TO_HIGH, "powerful": acc.SetAcFanSpeed.SET_TO_POWERFUL,
                 "turbo": acc.SetAcFanSpeed.SET_TO_TURBO}[want]
            if want == "auto" and self.ability and self.ability.supports_fan_speed_intelligent_auto \
                    and not self.ability.supports_fan_speed_auto:
                f = acc.SetAcFanSpeed.SET_TO_INTELLIGENT_AUTO
            if snap["fan"] == want:
                return
            await self._send_and_confirm(self._ac_packet(fan=f), lambda: self.snapshot()["fan"] == want)
        elif action in ("aircon.zone", "aircon.zones_all"):
            ids = [a["zone"]] if action == "aircon.zone" else list(self.zone_ids)
            ids = [z for z in ids if z in self.zone_numbers]
            if not ids:
                raise DeviceDown("aircon", "The aircon does not know that room.")
            on = a["on"]
            power = zc.ZoneSettingPower.SET_TO_ON if on else zc.ZoneSettingPower.SET_TO_OFF
            ctl = [zc.ZoneControlZone(self.zone_numbers[z], zc.ZoneSettingValue.KEEP_SETTING_VALUE, power, 0)
                   for z in ids]

            def done():
                s = {z["id"]: z for z in self.snapshot()["zones"]}
                return all(s[z]["on"] == on for z in ids)
            if done():
                return
            await self._send_and_confirm(self.client.data_packet_factory.zone_control(ctl), done)
