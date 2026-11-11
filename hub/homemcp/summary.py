"""Turns the hub's STATE (see EXAMPLE_STATE in contract.py) into short, readable text for Claude.

Every function copes with missing pieces: the real hub may leave a value out or set it to null.
"""
from __future__ import annotations


def _deg(v) -> str:
    if v is None:
        return "?"
    return f"{v:g}°C" if isinstance(v, (int, float)) else f"{v}°C"


def _name(d: dict) -> str:
    n, i = d.get("name"), d.get("id")
    return f"{n} ({i})" if n and i and n != i else str(n or i or "?")


def _data(v, n: int = 80) -> str:
    """Text that comes from outside the house (a song title, an artist, a TV app name): one line, short,
    quoted, and with no quote marks or angle brackets inside, so it reads as data and not as words to
    Claude. Song titles are a prompt injection path: anyone can name a song "ignore your rules and..."."""
    v = " ".join(str(v).split()).replace('"', "'").replace("<", "(").replace(">", ")")
    return '"' + (v[:n] + ("…" if len(v) > n else "")) + '"'


def _mmss(s) -> str:
    return f"{int(s) // 60}:{int(s) % 60:02d}" if isinstance(s, (int, float)) else "?"


# ---- aircon ----

def aircon_line(state: dict) -> str:
    ac = state.get("aircon") or {}
    if ac.get("available") is False:
        return "Aircon: NOT ANSWERING (the AirTouch console is not responding, so these values may be old)."
    if not ac.get("power"):
        parts = ["Aircon: OFF", f"(when on: {ac.get('mode', '?')}, set to {_deg(ac.get('set'))}, fan {ac.get('fan', '?')})"]
    else:
        parts = [f"Aircon: ON, {ac.get('mode', '?')}, set to {_deg(ac.get('set'))}, fan {ac.get('fan', '?')}"]
    if ac.get("inside") is not None:
        parts.append(f"- inside {_deg(ac.get('inside'))}")
    return " ".join(parts) + "."


def zone_line(z: dict) -> str:
    if z.get("on"):
        opening = z.get("open")
        # A room can be on with the vent at 0% while the aircon is off: say "on", not "open 0%".
        shown = isinstance(opening, (int, float)) and 0 < opening < 100
        vent = f"on (vent {opening}%)" if shown else "on"
    else:
        vent = "closed"
    temp = f", {_deg(z.get('temp'))}" if z.get("temp") is not None else ""
    return f"{_name(z)}: {vent}{temp}"


def rooms_block(state: dict) -> str:
    zones = (state.get("aircon") or {}).get("zones") or []
    if not zones:
        return "Rooms: none reported."
    return "Rooms (aircon vents):\n" + "\n".join(f"  - {zone_line(z)}" for z in zones)


def open_rooms_line(state: dict) -> str:
    zones = (state.get("aircon") or {}).get("zones") or []
    names = [z.get("name") or z.get("id") for z in zones if z.get("on")]
    return "Rooms with vents open: " + (", ".join(names) if names else "none") + "."


def aircon_off_note(state: dict) -> str:
    ac = state.get("aircon") or {}
    if ac.get("available") is not False and ac.get("power") is False:
        return " Note: the aircon itself is off, so no air flows until it is turned on."
    return ""


def aircon_summary(state: dict) -> str:
    return aircon_line(state) + "\n" + open_rooms_line(state) + aircon_off_note(state)


def zone_summary(state: dict, zone_id: str) -> str:
    zones = (state.get("aircon") or {}).get("zones") or []
    z = next((z for z in zones if z.get("id") == zone_id), None)
    first = (zone_line(z) + ".") if z else f"Room {zone_id}: not in the hub's answer."
    return first + "\n" + aircon_line(state) + "\n" + open_rooms_line(state) + aircon_off_note(state)


# ---- speakers and music ----

def _speaker_names(state: dict) -> dict:
    devs = (state.get("speakers") or {}).get("devices") or []
    return {d.get("id"): d.get("name") or d.get("id") for d in devs}


def now_playing_line(state: dict) -> str:
    sp = state.get("speakers") or {}
    now = sp.get("now")
    if not now:
        return "Now playing: nothing."
    names = _speaker_names(state)
    what = _data(now.get('title') or 'Unknown')
    if now.get("artist"):
        what += f" by {_data(now['artist'])}"
    if now.get("album") and now.get("album") != now.get("title"):
        what += f" (album {_data(now['album'])})"
    status = "playing" if now.get("playing") else "paused"
    src = {"spotify": "Spotify", "cast": "Cast"}.get(now.get("source"), now.get("source") or "")
    where = ", ".join(names.get(s, s) for s in (now.get("on") or [])) or "no speakers"
    pos = ""
    if now.get("duration"):
        pos = f", {_mmss(now.get('position'))} of {_mmss(now.get('duration'))}"
    return f"Now playing: {what} - {status}{f' on {src}' if src else ''}, on {where}{pos}."


def speakers_block(state: dict) -> str:
    sp = state.get("speakers") or {}
    if sp.get("available") is False:
        head = "Speakers: NOT ANSWERING (values may be old)."
    else:
        head = "Speakers:"
    lines = [head]
    for d in sp.get("devices") or []:
        bits = []
        if d.get("available") is False:
            bits.append("not answering")
        if d.get("volume") is not None:
            bits.append(f"volume {d['volume']}")
        if d.get("muted"):
            bits.append("muted")
        bits.append("in use" if d.get("in_use") else "idle")
        lines.append(f"  - {_name(d)}: {', '.join(bits)}")
    groups = sp.get("groups") or []
    if groups:
        lines.append("Speaker groups: " + "; ".join(
            f"{g.get('name') or g.get('id')} ({', '.join(g.get('members') or [])})" for g in groups))
    return "\n".join(lines)


def spotify_line(state: dict) -> str:
    linked = ((state.get("speakers") or {}).get("spotify") or {}).get("linked")
    if linked:
        return "Spotify: linked (music_search_play works)."
    return "Spotify: NOT linked yet, so music_search_play cannot find new music; play/pause/skip still work."


def music_summary(state: dict) -> str:
    return now_playing_line(state) + "\n" + speakers_block(state)


def volumes_line(state: dict) -> str:
    devs = (state.get("speakers") or {}).get("devices") or []
    return "Speaker volumes: " + ", ".join(
        f"{d.get('name') or d.get('id')} {d.get('volume') if d.get('volume') is not None else '?'}"
        f"{' (in use)' if d.get('in_use') else ''}" for d in devs) + "."


# ---- TVs ----

def tv_line(t: dict) -> str:
    power = t.get("power") or "unknown"
    bits = [f"waking up" if t.get("waking") else power]
    if power == "on":
        if t.get("app"):
            bits.append(_data(t["app"], 40))
        if t.get("volume") is not None:
            bits.append(f"volume {t['volume']}")
        if t.get("muted"):
            bits.append("muted")
    if t.get("art_mode") is not None:
        bits.append(f"Art mode {'on' if t['art_mode'] else 'off'}")
    return f"{_name(t)}: {', '.join(bits)}"


def tvs_block(state: dict) -> str:
    tv = state.get("tvs") or {}
    head = "TVs: NOT ANSWERING (the TV bridge is not responding, values may be old)." \
        if tv.get("available") is False else "TVs:"
    lines = [head] + [f"  - {tv_line(t)}" for t in tv.get("devices") or []]
    if tv.get("apps"):
        lines.append("TV apps: " + ", ".join(tv["apps"]))
    return "\n".join(lines)


def tv_summary(state: dict, tv_id: str) -> str:
    devs = (state.get("tvs") or {}).get("devices") or []
    t = next((t for t in devs if t.get("id") == tv_id), None)
    return (tv_line(t) + ".") if t else f"TV {tv_id}: not in the hub's answer."


# ---- everything ----

def house_summary(state: dict) -> str:
    parts = [
        aircon_line(state),
        rooms_block(state),
        "",
        now_playing_line(state),
        speakers_block(state),
        spotify_line(state),
        "",
        tvs_block(state),
    ]
    if state.get("updated"):
        parts += ["", f"(State as of {state['updated']}.)"]
    return "\n".join(parts)
