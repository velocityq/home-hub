"""Where the hub keeps its files, its settings and its keys.

~/.home-hub/            (HUB_HOME overrides, for tests)   mode 700
    config.json         non-secret settings, written with the defaults the first time
    keys.json           {"clients": {"wall": "...", "mcp": "...", "couch-tv": "..."}}  mode 600
                        (HUB_KEYS_FILE overrides)
    pair.json           the one pending pairing code (hashed), mode 600
    spotify.json        {"client_id": "..."}  made by the owner
    spotify-token.json  Spotify tokens, mode 600
    memory.json         what the hub learned (the AirTouch console's last address)
    logs/hub.log        rotating log, never holds a key
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import re
import secrets
import tempfile
import time

log = logging.getLogger("hub")

DEFAULT_CONFIG = {
    "port": 8790,
    "host": "0.0.0.0",
    # the AirTouch 5 console's address. null: the hub finds it with AirTouch's own discovery broadcast
    "airtouch_host": None,
    "airtouch_port": 9005,
    "bridge_url": "http://127.0.0.1:5400",
    "bridge_key": None,
    # contract speaker id -> the Cast friendly name and the name the screens show
    "speakers": {
        "lounge-room": {"cast": "Lounge Room Speaker", "name": "Lounge Room"},
        "theatre": {"cast": "THEATRE", "name": "Theatre"},
        "outside": {"cast": "OUTSIDE", "name": "Outside"},
    },
    "speaker_model": "WiFiCeilingSpeakerV2",
    # contract zone id -> the zone's name on the AirTouch console
    "zones": {
        "living": "Living", "media": "Media", "rumpus": "Rumpus", "master-bed": "Master Bed",
        "bed-2": "Bed 2", "bed-3": "Bed 3", "bed-4": "Bed 4",
    },
    "inside_zone": "living",
    "tv_names": {"living-room": "Living Room", "bedroom": "Bedroom", "frame": "The Frame"},
    "cors_origins": [],
    # other names this hub may be reached by (an IP address and this computer's own name always work)
    "allowed_hosts": [],
    # first names that get a card on the wall (event titles only), and the place name under the inside
    # temperature. Both empty by default: the wall then shows no names and no place.
    "people": [],
    "place": "",
    "spotify_redirect_uri": "http://127.0.0.1:8790/spotify/callback",
    "ask": {},
}

DEFAULT_CLIENTS = ("wall", "mcp", "couch-tv")


def home_dir():
    return os.path.expanduser(os.environ.get("HUB_HOME") or "~/.home-hub")


def path(*parts):
    return os.path.join(home_dir(), *parts)


def keys_path():
    return os.path.expanduser(os.environ.get("HUB_KEYS_FILE") or path("keys.json"))


def ensure_home():
    d = home_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    os.makedirs(os.path.join(d, "logs"), mode=0o700, exist_ok=True)
    return d


def read_json(p, default=None):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(p, data, mode=0o600):
    """Write a file atomically with the given mode (the file is never readable by others, even briefly)."""
    d = os.path.dirname(p) or "."
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_config():
    """The defaults, with config.json on top. Writes config.json with the defaults if it is missing."""
    ensure_home()
    p = path("config.json")
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    have = read_json(p)
    if have is None and not os.path.exists(p):
        write_json(p, DEFAULT_CONFIG, mode=0o644)
    elif isinstance(have, dict):
        for k, v in have.items():
            cfg[k] = v
    origins = cfg.get("cors_origins") or []
    if not isinstance(origins, list):
        origins = []
    clean = [o for o in origins if isinstance(o, str) and o and o != "*" and "*" not in o]
    if len(clean) != len(origins):
        log.warning("config: cors_origins may not hold '*'; those entries are ignored")
    cfg["cors_origins"] = clean
    if not cfg.get("bridge_key"):
        cfg["bridge_key"] = None
    return cfg


# ---------------- keys ----------------

class Keys:
    """The client keys. Re-reads keys.json when it changes. Compares in constant time."""

    def __init__(self, p=None):
        self.path = p or keys_path()
        self._mtime = None
        self._clients: dict[str, str] = {}
        self.ensure()
        self.reload(force=True)

    def ensure(self):
        if os.path.exists(self.path):
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            return
        ensure_home()
        clients = {name: secrets.token_urlsafe(32) for name in DEFAULT_CLIENTS}
        write_json(self.path, {"clients": clients})
        log.info("keys: made %s with keys for %s", self.path, ", ".join(DEFAULT_CLIENTS))

    def reload(self, force=False):
        try:
            m = os.stat(self.path).st_mtime_ns
        except OSError:
            self._clients = {}
            return
        if not force and m == self._mtime:
            return
        data = read_json(self.path, {}) or {}
        clients = data.get("clients") if isinstance(data, dict) else None
        self._clients = {str(n): str(k) for n, k in (clients or {}).items() if isinstance(k, str) and len(k) >= 16}
        self._mtime = m

    def who(self, key):
        """The client name for this key, or None. Every key is compared, in constant time."""
        self.reload()
        if not isinstance(key, str) or not key:
            return None
        kb = key.encode()
        found = None
        for name, k in self._clients.items():
            if hmac.compare_digest(kb, k.encode()):
                found = name
        return found

    def names(self):
        self.reload()
        return sorted(self._clients)

    def add(self, name):
        """Add a client with a new key. Returns (name, key). The name is made unique."""
        self.reload(force=True)
        data = read_json(self.path, {}) or {}
        clients = data.get("clients") or {}
        base = re.sub(r"[^a-z0-9-]+", "-", (name or "device").lower()).strip("-")[:40] or "device"
        final, n = base, 2
        while final in clients:
            final, n = f"{base}-{n}", n + 1
        key = secrets.token_urlsafe(32)
        clients[final] = key
        data["clients"] = clients
        write_json(self.path, data)
        self.reload(force=True)
        return final, key

    def revoke(self, name):
        """Remove one client's key. The running hub notices the file change and refuses it at once.
        Returns True if the client existed."""
        self.reload(force=True)
        data = read_json(self.path, {}) or {}
        clients = data.get("clients") or {}
        if name not in clients:
            return False
        del clients[name]
        data["clients"] = clients
        write_json(self.path, data)
        self.reload(force=True)
        return True


# ---------------- pairing ----------------

PAIR_TTL = 600
PAIR_TRIES = 5


def _hash_code(code, salt):
    return hashlib.sha256((salt + ":" + code).encode()).hexdigest()


def new_pair_code():
    """Make a one-time 6 digit code, good for 10 minutes. Only its hash is stored."""
    ensure_home()
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(8)
    write_json(path("pair.json"), {"hash": _hash_code(code, salt), "salt": salt,
                                   "expires": time.time() + PAIR_TTL, "tries": 0})
    return code


def check_pair_code(code):
    """True if the code is the pending one. A wrong try counts; after 5 the code is gone."""
    p = path("pair.json")
    data = read_json(p)
    if not isinstance(data, dict):
        return False
    if time.time() > data.get("expires", 0) or data.get("tries", 0) >= PAIR_TRIES:
        _drop(p)
        return False
    good = isinstance(code, str) and re.fullmatch(r"\d{6}", code) is not None and hmac.compare_digest(
        _hash_code(code, data.get("salt", "")), data.get("hash", ""))
    if good:
        _drop(p)
        return True
    data["tries"] = data.get("tries", 0) + 1
    if data["tries"] >= PAIR_TRIES:
        _drop(p)
    else:
        write_json(p, data)
    return False


def _drop(p):
    try:
        os.unlink(p)
    except OSError:
        pass


# ---------------- memory (things the hub learned) ----------------

def remember(key, value):
    p = path("memory.json")
    data = read_json(p, {}) or {}
    data[key] = value
    write_json(p, data)


def recall(key, default=None):
    return (read_json(path("memory.json"), {}) or {}).get(key, default)


# ---------------- logging ----------------

class _NoSecrets(logging.Filter):
    """Belt and braces: never let a ?key= or a Bearer value reach the log."""
    pat = re.compile(r"(key=|Bearer\s+|\"key\":\s*\")([A-Za-z0-9_\-]{6,})")

    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = self.pat.sub(lambda m: m.group(1) + "***", msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


def setup_logging(to_file=True, level=logging.INFO):
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    flt = _NoSecrets()
    handlers = [logging.StreamHandler()]
    if to_file:
        ensure_home()
        handlers.append(logging.handlers.RotatingFileHandler(path("logs", "hub.log"), maxBytes=1_000_000,
                                                             backupCount=5))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(flt)
        root.addHandler(h)
    for noisy in ("pychromecast", "zeroconf", "airtouch5py", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
