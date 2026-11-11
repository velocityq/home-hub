"""Personal views on the wall: who is standing there, and each person's card.

Rules (PLAN-NOTES.md, People and privacy): the card shows event TITLES and times only, never a
location, description, attendee or link. No PIN. Face recognition happens on the tablet; the hub only
ever hears a name (or nobody) and whether it came from a face or a tap.

Who has a card: config.json "people", a list of first names (empty by default: no cards, no name
buttons). "place" is the place name shown under the inside temperature (empty by default).

Calendars, per person, from two places:
  - config.json "personal": {"<Name>": {"calendars": [{"name": "Work", "snapshot": "<path to a JSON
    file with an "events" list>"}]}}, for a calendar something else on this computer already keeps
    as a file.
  - ~/.home-hub/personal.json (mode 600): private calendar addresses (iCal), added with
    `python -m hubserver calendar NAME`, which reads the address without showing it. Never in git.
Ring and parcels have a slot and say "Not connected yet".
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import time

from . import config as cfgmod

log = logging.getLogger("hub.personal")

HOWS = ("face", "tap")
MAX_PEOPLE = 8
NAME_RE = re.compile(r"[A-Za-z][A-Za-z' -]{0,23}")


def people_from(cfg):
    """The names in config.json "people": first names only, at most 8, no repeats."""
    out = []
    for n in (cfg or {}).get("people") or []:
        if isinstance(n, str) and NAME_RE.fullmatch(n.strip()) and n.strip() not in out:
            out.append(n.strip())
    return out[:MAX_PEOPLE]


def place_from(cfg):
    p = (cfg or {}).get("place")
    return " ".join(p.split())[:40] if isinstance(p, str) else ""
DAYS = 7               # how far ahead the card looks
MAX_EVENTS = 8
ICS_TTL = 600          # seconds an iCal download is reused
ICS_MAX = 5 * 1024 * 1024
SECRETS = "personal.json"


def _local_tz():
    return dt.datetime.now().astimezone().tzinfo


def _parse_start(s):
    """ISO date or date-time -> (aware datetime, all_day)."""
    if not isinstance(s, str) or not s:
        return None, False
    try:
        if len(s) == 10:
            d = dt.date.fromisoformat(s)
            return dt.datetime(d.year, d.month, d.day, tzinfo=_local_tz()), True
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=_local_tz())
        return t, False
    except ValueError:
        return None, False


def _event(title, start, all_day, cal):
    """The only fields that ever leave the hub for a card."""
    title = " ".join(str(title or "").split())[:80] or "(no title)"
    return {"title": title, "start": start.isoformat(), "allDay": bool(all_day), "calendar": cal}


def read_snapshot(path, name, now, until):
    """Events from a JSON file the iMac already keeps. Returns (events, error)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return [], "not found"
    except PermissionError:
        return [], "the hub may not read that folder"
    except (OSError, ValueError) as e:
        return [], f"unreadable ({type(e).__name__})"
    out = []
    for ev in (data.get("events") or []) if isinstance(data, dict) else []:
        if not isinstance(ev, dict):
            continue
        start, all_day = _parse_start(ev.get("start"))
        if start is None:
            continue
        end_of = start + (dt.timedelta(days=1) if (all_day or ev.get("allDay")) else dt.timedelta(hours=1))
        if end_of < now or start > until:
            continue
        out.append(_event(ev.get("title"), start, all_day or bool(ev.get("allDay")), name))
    fetched = data.get("fetched") if isinstance(data, dict) else None
    stale = None
    if isinstance(fetched, str):
        f_at, _ = _parse_start(fetched)
        if f_at and (now - f_at).total_seconds() > 6 * 3600:
            stale = "last updated " + f_at.astimezone(_local_tz()).strftime("%-d %b %-I:%M %p")
    return out, stale


def parse_ics(text, name, now, until):
    """Events from iCal text, repeating events included. Titles and start times only."""
    import icalendar
    import recurring_ical_events
    cal = icalendar.Calendar.from_ical(text)
    out = []
    for ev in recurring_ical_events.of(cal).between(now - dt.timedelta(days=1), until):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        s = ev.get("DTSTART")
        if s is None:
            continue
        v = s.dt
        if isinstance(v, dt.datetime):
            start, all_day = (v if v.tzinfo else v.replace(tzinfo=_local_tz())), False
            end_v = ev.get("DTEND").dt if ev.get("DTEND") is not None else start + dt.timedelta(hours=1)
            end = end_v if isinstance(end_v, dt.datetime) else start + dt.timedelta(hours=1)
            if end.tzinfo is None:
                end = end.replace(tzinfo=_local_tz())
        else:
            start, all_day = dt.datetime(v.year, v.month, v.day, tzinfo=_local_tz()), True
            end = start + dt.timedelta(days=1)
        if end < now or start > until:
            continue
        out.append(_event(ev.get("SUMMARY"), start, all_day, name))
    return out


def load_secrets():
    data = cfgmod.read_json(cfgmod.path(SECRETS), {}) or {}
    return data if isinstance(data, dict) else {}


def save_calendar_address(person, name, url, people=None):
    """Used by `python -m hubserver calendar`. The file is mode 600 in ~/.home-hub, never in git."""
    if people is not None and person not in people:
        raise ValueError(f"the people are {', '.join(people) or 'not set (add them to config.json)'}")
    url = url.strip()
    if url.startswith("webcal://"):  # privacy-scan: allow (the iCal scheme, not a link)
        url = "https://" + url[len("webcal://"):]  # privacy-scan: allow
    if not url.startswith("https://") or " " in url:
        raise ValueError("that does not look like a private calendar address (it should start with https:// or webcal://)")  # privacy-scan: allow
    data = load_secrets()
    cals = [c for c in data.get(person, []) if isinstance(c, dict) and c.get("name") != name]
    cals.append({"name": name, "ics": url})
    data[person] = cals
    cfgmod.write_json(cfgmod.path(SECRETS), data)


def remove_calendar(person, name):
    data = load_secrets()
    before = len(data.get(person, []))
    data[person] = [c for c in data.get(person, []) if c.get("name") != name]
    cfgmod.write_json(cfgmod.path(SECRETS), data)
    return len(data[person]) < before


class Personal:
    def __init__(self, cfg, fetch=None, clock=None):
        self.cfg = cfg
        self.people = people_from(cfg)
        self.place = place_from(cfg)
        self.presence = {"who": None, "how": None, "at": None}
        self._fetch = fetch            # tests: async (url) -> text
        self._clock = clock or (lambda: dt.datetime.now().astimezone())
        self._ics_cache = {}           # url -> (time, (text, error))

    # ---------- who is here ----------
    def set_presence(self, who, how, client):
        if who is not None and who not in self.people:
            raise ValueError("unknown person")
        if how not in HOWS:
            raise ValueError("how must be face or tap")
        changed = who != self.presence["who"]
        self.presence = {"who": who, "how": how if who else None, "at": time.time()}
        if changed:
            log.info("presence: %s (%s, from %s)", who or "nobody", how, client)
        return self.presence

    # ---------- a person's card ----------
    def calendars(self, person):
        conf = (self.cfg.get("personal") or {}).get(person) or {"calendars": []}
        cals = [dict(c) for c in conf.get("calendars", []) if isinstance(c, dict)]
        for c in load_secrets().get(person, []):
            if isinstance(c, dict) and c.get("ics"):
                cals.append({"name": c.get("name") or "Calendar", "ics": c["ics"]})
        return cals

    async def _ics(self, url, name, now, until):
        hit = self._ics_cache.get(url)
        if hit and time.time() - hit[0] < ICS_TTL:
            text, err = hit[1]
        else:
            text, err = None, None
            try:
                text = await (self._fetch(url) if self._fetch else self._download(url))
            except Exception as e:                      # never log the address: it is a secret
                err = f"could not download ({type(e).__name__})"
                log.warning("calendar %s: %s", name, err)
            self._ics_cache[url] = (time.time(), (text, err))
        if err:
            return [], err
        try:
            return await asyncio.to_thread(parse_ics, text, name, now, until), None
        except Exception as e:
            log.warning("calendar %s: could not read it (%s)", name, type(e).__name__)
            return [], "could not read it"

    @staticmethod
    async def _download(url):
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url) as r:
                r.raise_for_status()
                body = await r.content.read(ICS_MAX + 1)
                if len(body) > ICS_MAX:
                    raise ValueError("too big")
                return body.decode("utf-8", "replace")

    async def card(self, person):
        if person not in self.people:
            raise KeyError(person)
        now = self._clock()
        start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        until = start_today + dt.timedelta(days=DAYS)
        events, sources = [], []
        for c in self.calendars(person):
            name = str(c.get("name") or "Calendar")[:40]
            if c.get("snapshot"):
                evs, note = await asyncio.to_thread(read_snapshot, os.path.expanduser(c["snapshot"]), name, now, until)
                ok = note in (None,) or note.startswith("last updated")
                sources.append({"name": name, "connected": ok and note != "not found", "note": note})
            elif c.get("ics"):
                evs, note = await self._ics(c["ics"], name, now, until)
                sources.append({"name": name, "connected": note is None, "note": note})
            else:
                continue
            events.extend(evs)
        events.sort(key=lambda e: e["start"])
        return {
            "person": person,
            "calendar": {"sources": sources, "events": events[:MAX_EVENTS], "more": max(0, len(events) - MAX_EVENTS),
                         "days": DAYS},
            "ring": {"connected": False, "note": "Not connected yet"},
            "parcels": {"connected": False, "note": "Not connected yet"},
        }
