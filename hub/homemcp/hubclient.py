"""Talks to the home hub over HTTP. Only two routes are used: GET /api/state and POST /api/action.

Every failure becomes a HubError with plain words a person can read. The key is never put in a
message, a log line or a result.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import anyio

DEFAULT_URL = "http://127.0.0.1:8790"
STATE_TIMEOUT = 10
ACTION_TIMEOUT = 45          # a TV can take a while to wake up

DEVICE_WORDS = {"aircon": "the aircon", "speakers": "the speakers", "tvs": "the TVs"}


class HubError(Exception):
    """Something went wrong talking to the hub. str(e) is plain words, safe to show."""


def hub_url() -> str:
    return (os.environ.get("HUB_URL") or DEFAULT_URL).rstrip("/")


def keys_file() -> Path:
    return Path(os.environ.get("HUB_KEYS_FILE") or Path.home() / ".home-hub" / "keys.json")


def load_key() -> str:
    """HUB_KEY, else the "mcp" client in the keys file. Raises HubError if there is none."""
    key = (os.environ.get("HUB_KEY") or "").strip()
    if key:
        return key
    path = keys_file()
    try:
        data = json.loads(path.read_text())
        key = str(((data or {}).get("clients") or {}).get("mcp") or "").strip()
    except FileNotFoundError:
        key = ""
    except (OSError, ValueError, AttributeError):
        raise HubError(f"The hub keys file ({path}) could not be read. Check it is valid JSON.") from None
    if not key:
        raise HubError("These tools have no hub key yet. Set HUB_KEY, or add an \"mcp\" key under "
                       f"\"clients\" in {path}.")
    return key


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # the hub is local: never a proxy


def _request(method: str, path: str, body: dict | None, timeout: float) -> dict:
    key = load_key()
    url = hub_url() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json",
        **({"Content-Type": "application/json"} if data is not None else {})})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        raise HubError(f"The home hub is not answering at {hub_url()}. Is it running?") from None
    try:
        answer = json.loads(raw or b"{}")
    except ValueError:
        answer = {}
    if not isinstance(answer, dict):
        answer = {}
    if status == 200 and answer.get("ok"):
        return answer
    raise HubError(_plain_error(status, answer))


def _plain_error(status: int, answer: dict) -> str:
    said = str(answer.get("error") or "").strip()
    if status == 401:
        return ("The hub did not accept the key these tools use. The \"mcp\" key may be wrong or "
                "out of date in the keys file (or HUB_KEY).")
    if status == 409:
        if answer.get("needs") == "spotify":
            return ((said or "Spotify is not linked yet.") + " Spotify has to be linked once, by opening "
                    "/spotify/login on the hub from the iMac itself. Until then, music_control and "
                    "music_choose_speakers still work on whatever is already playing.")
        return said or "The hub cannot do that right now."
    if status == 503:
        dev = DEVICE_WORDS.get(answer.get("device"), "a device")
        return (said or f"{dev[0].upper()}{dev[1:]} is not answering.") + \
            f" The hub could not reach {dev}; it may be off or offline. Nothing was changed."
    if status == 400:
        return f"The hub refused that: {said or 'the request broke the hub contract.'}"
    if status == 404:
        return "The hub does not know that route. It may be an older or newer version than these tools."
    return f"The hub had a problem (status {status}){': ' + said if said else '.'}"


async def get_state() -> dict:
    answer = await anyio.to_thread.run_sync(_request, "GET", "/api/state", None, STATE_TIMEOUT)
    state = answer.get("state")
    if not isinstance(state, dict):
        raise HubError("The hub answered without a house state.")
    return state


async def run_action(action: str, args: dict) -> dict:
    """POST /api/action. Returns the new state. The caller has already checked it with contract.validate()."""
    answer = await anyio.to_thread.run_sync(
        _request, "POST", "/api/action", {"action": action, "args": args}, ACTION_TIMEOUT)
    state = answer.get("state")
    return state if isinstance(state, dict) else {}
