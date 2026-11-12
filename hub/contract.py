"""The home hub contract: every action, its arguments, and the shape of the state.

This file is shared by the real hub (hub/server), the fake hub (hub/fake_hub.py), the Claude tools
(hub/homemcp) and the Ask module (hub/ask). Do not change it inside one part: a change here is a change
for everyone. See CONTRACT.md for the plain-words version.
"""
from __future__ import annotations

import re

API_VERSION = 1
DEFAULT_PORT = 8790

MODES = ["cool", "heat", "fan", "dry", "auto"]
FAN_SPEEDS = ["auto", "quiet", "low", "medium", "high", "powerful", "turbo"]
TEMP_MIN, TEMP_MAX = 16, 30

# Stable ids. The hub maps them to the real devices.
ZONES = ["living", "media", "rumpus", "master-bed", "bed-2", "bed-3", "bed-4"]
SPEAKERS = ["lounge-room", "theatre", "outside"]
TVS = ["living-room", "bedroom", "frame"]
# The remote buttons tv.key can press. "home" is couch-tv's own home screen on that TV.
TV_KEYS = ["up", "down", "left", "right", "ok", "back", "home", "play_pause", "rewind", "fast_forward"]


class ContractError(ValueError):
    """A request that breaks the contract. The message is plain words, safe to show a person."""


def _bool(v, name):
    if isinstance(v, bool):
        return v
    raise ContractError(f"{name} must be true or false")


def _int(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
        raise ContractError(f"{name} must be a whole number")
    v = int(v)
    if not lo <= v <= hi:
        raise ContractError(f"{name} must be between {lo} and {hi}")
    return v


def _choice(v, name, options):
    if v not in options:
        raise ContractError(f"{name} must be one of: {', '.join(options)}")
    return v


def _text(v, name, max_len=200):
    if not isinstance(v, str) or not v.strip():
        raise ContractError(f"{name} must be some text")
    if len(v) > max_len:
        raise ContractError(f"{name} is too long (at most {max_len} characters)")
    return v.strip()


def _spotify_id(v, name):
    v = _text(v, name, 40)
    if not re.fullmatch(r"[A-Za-z0-9]{10,40}", v):
        raise ContractError(f"{name} is not a Spotify id")
    return v


def _spotify_uri(v, name):
    v = _text(v, name, 80)
    if not re.fullmatch(r"spotify:(track|album|artist|playlist):[A-Za-z0-9]{10,40}|spotify:user:[A-Za-z0-9._-]{1,40}:collection", v):
        raise ContractError(f"{name} is not a Spotify link")
    return v


def _speaker_list(v, name):
    if not isinstance(v, list) or not v:
        raise ContractError(f"{name} must be a list of one or more speakers")
    out = []
    for s in v:
        _choice(s, name, SPEAKERS)
        if s not in out:
            out.append(s)
    return out


# action name -> (description, {arg: validator}, required args)
# A validator takes the value and returns the cleaned value or raises ContractError.
ACTIONS: dict[str, tuple[str, dict, set]] = {
    # ---- aircon ----
    "aircon.power": ("Turn the whole aircon on or off.",
                     {"on": lambda v: _bool(v, "on")}, {"on"}),
    "aircon.set_temp": (f"Set the target temperature, {TEMP_MIN} to {TEMP_MAX} degrees.",
                        {"value": lambda v: _int(v, "value", TEMP_MIN, TEMP_MAX)}, {"value"}),
    "aircon.nudge": ("Move the target temperature up or down by 1 or 2 degrees.",
                     {"delta": lambda v: _int(v, "delta", -2, 2)}, {"delta"}),
    "aircon.mode": ("Set the mode: " + ", ".join(MODES) + ". Also turns the aircon on.",
                    {"mode": lambda v: _choice(v, "mode", MODES)}, {"mode"}),
    "aircon.fan": ("Set the fan speed: " + ", ".join(FAN_SPEEDS) + ". The hub picks the nearest speed the unit has.",
                   {"speed": lambda v: _choice(v, "speed", FAN_SPEEDS)}, {"speed"}),
    "aircon.zone": ("Open (on) or close (off) one room's vent. Rooms: " + ", ".join(ZONES) + ".",
                    {"zone": lambda v: _choice(v, "zone", ZONES), "on": lambda v: _bool(v, "on")}, {"zone", "on"}),
    "aircon.zones_all": ("Open or close every room's vent.",
                         {"on": lambda v: _bool(v, "on")}, {"on"}),
    # ---- speakers and music ----
    "music.play": ("Play or carry on playing.", {}, set()),
    "music.pause": ("Pause the music.", {}, set()),
    "music.next": ("Skip to the next song.", {}, set()),
    "music.previous": ("Go back to the start of the song, or the song before.", {}, set()),
    "music.speakers": ("Choose which speakers play the music now (one, two or all three).",
                       {"speakers": lambda v: _speaker_list(v, "speakers")}, {"speakers"}),
    "music.start": ("Start music straight away from what he listened to last ('recent'), his Liked Songs ('liked') "
                    "his main playlist ('main'), his Discover Weekly ('discover'), one of his playlists ('playlist' "
                    "plus its Spotify id) or any song, album, artist or playlist ('uri' plus its Spotify uri). "
                    "Needs Spotify linked.",
                    {"what": lambda v: _choice(v, "what", ["recent", "liked", "playlist", "main", "discover", "uri"]),
                     "playlist": lambda v: _spotify_id(v, "playlist"),
                     "uri": lambda v: _spotify_uri(v, "uri"),
                     "speakers": lambda v: _speaker_list(v, "speakers")}, {"what"}),
    "music.search_play": ("Find music on Spotify by words (a song, an artist, a playlist, a mood) and play it. "
                          "Needs Spotify linked.",
                          {"query": lambda v: _text(v, "query", 120),
                           "speakers": lambda v: _speaker_list(v, "speakers")}, {"query"}),
    "speakers.volume": ("Set one speaker's volume, 0 to 100, or 'all' for every speaker that is playing.",
                        {"speaker": lambda v: _choice(v, "speaker", SPEAKERS + ["all"]),
                         "value": lambda v: _int(v, "value", 0, 100)}, {"speaker", "value"}),
    # ---- TVs ----
    "tv.power": ("Turn a TV on or off. TVs: " + ", ".join(TVS) + ".",
                 {"tv": lambda v: _choice(v, "tv", TVS), "on": lambda v: _bool(v, "on")}, {"tv", "on"}),
    "tv.volume": ("Turn a TV's volume up or down by 1 to 10 steps.",
                  {"tv": lambda v: _choice(v, "tv", TVS), "delta": lambda v: _int(v, "delta", -10, 10)}, {"tv", "delta"}),
    "tv.mute": ("Mute or unmute a TV.",
                {"tv": lambda v: _choice(v, "tv", TVS), "muted": lambda v: _bool(v, "muted")}, {"tv", "muted"}),
    "tv.launch": ("Open an app on a TV, by its name (for example YouTube, Netflix).",
                  {"tv": lambda v: _choice(v, "tv", TVS), "app": lambda v: _text(v, "app", 60)}, {"tv", "app"}),
    "tv.play": ("Find a show or film by its title and play it on a TV.",
                {"tv": lambda v: _choice(v, "tv", TVS), "title": lambda v: _text(v, "title", 120)}, {"tv", "title"}),
    "tv.key": ("Press one remote button on a TV: " + ", ".join(TV_KEYS) + ".",
               {"tv": lambda v: _choice(v, "tv", TVS), "key": lambda v: _choice(v, "key", TV_KEYS)}, {"tv", "key"}),
    "tv.art_mode": ("Turn Art mode on or off on the Frame TV.",
                    {"tv": lambda v: _choice(v, "tv", ["frame"]), "on": lambda v: _bool(v, "on")}, {"tv", "on"}),
}


def validate(action, args):
    """Check one action. Returns (action, cleaned_args). Raises ContractError in plain words."""
    if not isinstance(action, str) or action not in ACTIONS:
        raise ContractError("That is not something the hub can do.")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ContractError("args must be an object")
    _, spec, required = ACTIONS[action]
    unknown = set(args) - set(spec)
    if unknown:
        raise ContractError(f"Unknown argument: {', '.join(sorted(unknown))}")
    missing = required - set(args)
    if missing:
        raise ContractError(f"Missing argument: {', '.join(sorted(missing))}")
    return action, {k: spec[k](v) for k, v in args.items()}


def describe_actions():
    """The action list as plain data, for GET /api/actions and for Claude prompts."""
    return [{"action": name, "description": desc, "args": sorted(spec), "required": sorted(req)}
            for name, (desc, spec, req) in ACTIONS.items()]


# ---- the shape of GET /api/state (the fake hub builds exactly this) ----
EXAMPLE_STATE = {
    "version": API_VERSION,
    "updated": "2026-11-10T13:00:00+11:00",
    "aircon": {
        "available": True,          # false when the AirTouch console does not answer
        "power": True,
        "mode": "cool",
        "set": 22,
        "fan": "auto",
        "fan_speeds": ["auto", "low", "medium", "high"],   # the speeds this unit really has
        "inside": 23.6,             # the Living room sensor, or null
        "zones": [
            {"id": "living", "name": "Living", "on": False, "temp": 23.6, "open": 0},
            {"id": "media", "name": "Media", "on": True, "temp": 24.2, "open": 100},
            # ... all 7, in the order of ZONES. "open" is the vent opening in percent.
        ],
    },
    "speakers": {
        "available": True,
        "devices": [
            {"id": "lounge-room", "name": "Lounge Room", "available": True, "volume": 55, "muted": False, "in_use": True},
            {"id": "theatre", "name": "Theatre", "available": True, "volume": 40, "muted": False, "in_use": False},
            {"id": "outside", "name": "Outside", "available": True, "volume": 35, "muted": False, "in_use": True},
        ],
        # Google Home speaker groups the hub has found, matched by their members. Empty until they exist.
        "groups": [{"id": "lounge-room+outside", "name": "Lounge + Outside", "members": ["lounge-room", "outside"]}],
        "now": {                    # null when nothing is playing or paused
            "title": "Harvest Moon", "artist": "Neil Young", "album": "Harvest Moon",
            "art": "https://i.scdn.co/image/...",   # or null
            "duration": 303, "position": 96,          # seconds, or null
            "playing": True,
            "source": "spotify",                       # "spotify" or "cast"
            "on": ["lounge-room", "outside"],          # where it is playing
        },
        "spotify": {"linked": False},                  # true once Spotify is linked on the iMac
    },
    "tvs": {
        "available": True,          # false when the couch-tv bridge does not answer
        "devices": [
            {"id": "living-room", "name": "Living Room", "kind": "android", "power": "on",
             "app": "YouTube", "volume": 18, "muted": False, "art_mode": None, "waking": False},
            {"id": "bedroom", "name": "Bedroom", "kind": "android", "power": "off",
             "app": None, "volume": None, "muted": None, "art_mode": None, "waking": False},
            {"id": "frame", "name": "The Frame", "kind": "samsung", "power": "off",
             "app": None, "volume": None, "muted": None, "art_mode": True, "waking": False},
        ],
        "apps": ["YouTube", "Netflix", "Stan", "ABC iview", "SBS On Demand", "Disney+", "Prime Video", "Live TV"],
    },
}
