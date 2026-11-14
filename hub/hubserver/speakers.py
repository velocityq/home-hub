"""The 3 ceiling speakers: Cast for volume, what is playing and play/pause/skip; Spotify (when linked)
for what is playing, moving the music between speakers and finding music.

Groups: Cast cannot join speakers on the fly from here, so the owner makes Google Home speaker
groups. The hub finds them (any time, they can appear later), learns their members and matches
them by member set.
"""
from __future__ import annotations

import asyncio
import logging
import time

import contract as C

from .errors import Conflict, DeviceDown, NeedsSpotify, NothingPlaying
from .spotify import pick_result

log = logging.getLogger("hub.speakers")


def _join_names(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


class Speakers:
    def __init__(self, cfg, on_change=lambda: None, backend=None, spotify=None):
        self.cfg = cfg
        self.on_change = on_change
        self.backend = backend
        self.spotify = spotify
        self.names = {sid: cfg["speakers"].get(sid, {}).get("name", sid) for sid in C.SPEAKERS}
        self.cast_names = {sid: cfg["speakers"].get(sid, {}).get("cast", "") for sid in C.SPEAKERS}
        self.spotify_names = {sid: cfg["speakers"].get(sid, {}).get("spotify") for sid in C.SPEAKERS}
        # "music": "spotify" in config.json: no Cast ceiling speakers in this house. The music card is Spotify
        # itself: whatever is playing on the account, on any of its Spotify Connect devices (phone, computer,
        # TV, speaker), and music.device moves it between them.
        self.spotify_only = str(cfg.get("music") or "").lower() == "spotify"

    async def start(self):
        if not self.spotify_only:
            await asyncio.to_thread(self.backend.start)

    async def stop(self):
        if not self.spotify_only:
            await asyncio.to_thread(self.backend.stop)

    def _snap(self):
        return {"speakers": {}, "groups": []} if self.spotify_only else self.backend.snapshot()

    # ---------- reading ----------
    def _groups(self, snap):
        """Groups whose members are all our speakers, at least 2, one per member set."""
        out, seen = [], set()
        for g in snap["groups"]:
            members = g.get("members") or []
            if len(members) < 2 or any(m is None for m in members):
                continue
            ordered = [s for s in C.SPEAKERS if s in members]
            gid = "+".join(ordered)
            if gid in seen:
                continue
            seen.add(gid)
            out.append({"id": gid, "name": g.get("name") or " + ".join(self.names[s] for s in ordered),
                        "members": ordered, "_uuid": g["uuid"], "_row": g})
        return out

    def _spotify_target(self, device_name, groups):
        """Which of our speakers a Spotify device name is, or None."""
        n = (device_name or "").strip().lower()
        if not n:
            return None
        for sid in C.SPEAKERS:
            cands = {self.names[sid].lower(), self.cast_names[sid].lower()}
            if self.spotify_names[sid]:
                cands.add(self.spotify_names[sid].lower())
            if n in cands:
                return [sid]
        for g in groups:
            if (g["name"] or "").strip().lower() == n:
                return list(g["members"])
        return None

    def _cast_now(self, snap, groups):
        """(now, uuid) for the Cast session that is playing, groups first."""
        cands = [(g["_row"], g["members"]) for g in groups]
        cands += [(row, [sid]) for sid, row in snap["speakers"].items() if sid in C.SPEAKERS]
        best = None
        for row, on in cands:
            m = row.get("media")
            if not m or m.get("state") not in ("PLAYING", "PAUSED", "BUFFERING"):
                continue
            rank = 0 if m["state"] in ("PLAYING", "BUFFERING") else 1
            if best is None or rank < best[0]:
                best = (rank, row, on, m)
        if best is None:
            return None, None
        _, row, on, m = best
        return ({"title": m.get("title"), "artist": m.get("artist"), "album": m.get("album"), "art": m.get("art"),
                 "duration": m.get("duration"), "position": m.get("position"),
                 "playing": m["state"] in ("PLAYING", "BUFFERING"), "source": "cast", "on": on}, row["uuid"])

    def _spotify_now(self, groups):
        sp = self.spotify
        if not sp or not sp.linked or not sp.player:
            return None
        p = sp.player
        item, dev = p.get("item"), p.get("device") or {}
        if not item:
            return None
        on = [] if self.spotify_only else self._spotify_target(dev.get("name"), groups)
        if on is None or (not on and not self.spotify_only):
            return None
        if item.get("type") == "episode":
            artist = (item.get("show") or {}).get("name")
            album = None
            imgs = item.get("images") or (item.get("show") or {}).get("images") or []
        else:
            artist = ", ".join(a.get("name", "") for a in item.get("artists") or []) or None
            album = (item.get("album") or {}).get("name")
            imgs = (item.get("album") or {}).get("images") or []
        pos = p.get("progress_ms")
        if pos is not None and p.get("is_playing"):
            pos += (time.time() - sp.player_at) * 1000
        dur = item.get("duration_ms")
        if pos is not None and dur:
            pos = min(pos, dur)
        return {"title": item.get("name"), "artist": artist, "album": album,
                "art": imgs[0].get("url") if imgs else None,
                "duration": int(dur / 1000) if dur else None, "position": int(pos / 1000) if pos is not None else None,
                "playing": bool(p.get("is_playing")), "source": "spotify", "on": on,
                "shuffle": bool(p.get("shuffle_state")),
                "device": {"id": dev.get("id"), "name": dev.get("name"), "type": (dev.get("type") or "").lower(),
                           "volume": dev.get("volume_percent")} if dev.get("id") else None}

    def _now(self, snap=None):
        snap = snap or self._snap()
        groups = self._groups(snap)
        now = self._spotify_now(groups)
        if now is not None:
            return now, None, snap, groups
        now, uuid = self._cast_now(snap, groups)
        return now, uuid, snap, groups

    def snapshot(self):
        now, _, snap, groups = self._now()
        devices = []
        for sid in C.SPEAKERS:
            row = snap["speakers"].get(sid)
            playing_here = bool(row and row.get("media") and row["media"].get("state") in ("PLAYING", "PAUSED", "BUFFERING"))
            devices.append({
                "id": sid, "name": self.names[sid],
                "available": bool(row and row.get("connected")),
                "volume": row.get("volume") if row else None,
                "muted": row.get("muted") if row else None,
                "in_use": bool((now and sid in now["on"]) or playing_here),
            })
        if self.spotify_only:
            sp = self.spotify
            return {"available": bool(sp and sp.linked and not sp.last_error), "mode": "spotify", "devices": [],
                    "groups": [], "now": now, "spotify": self._spotify_state()}
        return {"available": any(d["available"] for d in devices), "devices": devices, "mode": "cast",
                "groups": [{"id": g["id"], "name": g["name"], "members": g["members"]} for g in groups],
                "now": now, "spotify": self._spotify_state()}

    def _spotify_state(self):
        linked = bool(self.spotify and self.spotify.linked)
        out = {"linked": linked}
        if linked:
            out["devices"] = [dict(d) for d in self.spotify.devs]
            q = self.spotify.quick
            out["playlists"] = q.get("playlists") or []
            last = q.get("last") or {}
            out["last"] = (f"{last['title']} · {last['artist']}" if last.get("title") and last.get("artist")
                           else last.get("title"))
        return out

    # ---------- doing ----------
    def _need_any(self, snap):
        if self.spotify_only:
            return
        if not any(r.get("connected") for r in snap["speakers"].values()):
            raise DeviceDown("speakers")

    async def _blocking(self, fn, *a, what="The speaker did not take the change."):
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *a), 15)
        except (LookupError, ConnectionError, TimeoutError, asyncio.TimeoutError) as e:
            raise DeviceDown("speakers", what) from e
        except Exception as e:
            log.warning("speakers: %s failed: %s %s", getattr(fn, "__name__", fn), type(e).__name__, e)
            raise DeviceDown("speakers", what) from e

    def _target(self, speakers, groups, snap):
        """(kind, cast uuid, spotify names, label) for a set of speakers. 409 when 2+ have no group."""
        if len(speakers) == 1:
            sid = speakers[0]
            row = snap["speakers"].get(sid)
            if not row or not row.get("connected"):
                raise DeviceDown("speakers", f"The {self.names[sid]} speaker is not answering.")
            names = [self.cast_names[sid], self.names[sid]] + ([self.spotify_names[sid]] if self.spotify_names[sid] else [])
            return "speaker", row["uuid"], names, self.names[sid]
        want = set(speakers)
        for g in groups:
            if set(g["members"]) == want:
                if not g["_row"].get("connected"):
                    raise DeviceDown("speakers", f"The {g['name']} speaker group is not answering.")
                return "group", g["_uuid"], [g["name"]], g["name"]
        ordered = [self.names[s] for s in C.SPEAKERS if s in want]
        raise Conflict(f"There is no speaker group for {_join_names(ordered)} yet. In the Google Home app, "
                       f"make a speaker group with just those speakers, then try again.")

    async def _spotify_device(self, names, label):
        devs = await self.spotify.devices()
        low = {n.strip().lower() for n in names if n}
        for d in devs:
            if (d.get("name") or "").strip().lower() in low and d.get("id"):
                return d["id"]
        raise Conflict(f"Spotify can't see {label} yet. On a phone, open Spotify, tap the speaker icon and pick "
                       f"{label} once. After that it works from here.")

    async def _settle_spotify(self, check, tries=8):
        for _ in range(tries):
            await asyncio.sleep(0.5)
            try:
                p = await self.spotify.refresh_player()
            except Exception:
                continue
            if check(p):
                return
        self.on_change()

    async def _settle_cast(self, check, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if check():
                return
            await asyncio.sleep(0.15)

    async def _play_here(self):
        """Spotify-only: the device to start music on. The one playing now, else the last one used, else the
        computer or phone Spotify lists first. 409 in plain words when there is none."""
        p = await self.spotify.refresh_player()
        dev = (p or {}).get("device") or {}
        if dev.get("id"):
            return dev["id"]
        devs = await self.spotify.refresh_devices()
        last = self.spotify.prefs().get("last_device")
        pick = next((d for d in devs if d["id"] == last), None) or next(
            (d for d in devs if d["type"] in ("computer", "smartphone")), None) or (devs[0] if devs else None)
        if not pick:
            raise Conflict("Spotify has nowhere to play. Open Spotify on your phone, computer or TV first.")
        return pick["id"]

    async def do(self, action, a):
        snap = self._snap()
        if action in ("music.device", "music.volume"):
            if not (self.spotify and self.spotify.linked):
                raise NeedsSpotify("Spotify is not linked yet. Link it on this computer first.")
            if action == "music.device":
                devs = await self.spotify.refresh_devices()
                d = next((x for x in devs if x["id"] == a["device"]), None)
                if d is None:
                    raise Conflict("Spotify can't see that device right now. Open Spotify on it, then try again.")
                if d["restricted"]:
                    raise Conflict(f"Spotify doesn't allow {d['name']} to be controlled from here.")
                p = self.spotify.player or {}
                if (p.get("device") or {}).get("id") == d["id"]:
                    return
                await self.spotify.transfer(d["id"], play=bool(p.get("is_playing")) or not p.get("item"))
                self.spotify.save_prefs(last_device=d["id"])
                await self._settle_spotify(lambda p: p and (p.get("device") or {}).get("id") == d["id"])
                await self.spotify.refresh_devices()
                return
            p = await self.spotify.refresh_player()
            dev = (p or {}).get("device") or {}
            if not dev.get("id"):
                raise NothingPlaying()
            if dev.get("supports_volume") is False:
                raise Conflict(f"{dev.get('name') or 'That device'} doesn't let Spotify change its volume.")
            await self.spotify.volume(a["value"], dev["id"])
            await self._settle_spotify(lambda p: p and ((p.get("device") or {}).get("volume_percent")) == a["value"], tries=4)
            return
        if self.spotify_only and action in ("speakers.volume", "music.speakers"):
            raise Conflict("This house plays music through Spotify. Pick a Spotify device instead.")
        if action == "speakers.volume":
            self._need_any(snap)
            now, *_ = self._now(snap)
            if a["speaker"] == "all":
                targets = [d["id"] for d in self.snapshot()["devices"] if d["in_use"]]
            else:
                targets = [a["speaker"]]
            for sid in targets:
                row = snap["speakers"].get(sid)
                if not row or not row.get("connected"):
                    raise DeviceDown("speakers", f"The {self.names[sid]} speaker is not answering.")
                await self._blocking(self.backend.set_volume, row["uuid"], a["value"])
            return

        if action in ("music.play", "music.pause", "music.next", "music.previous"):
            now, uuid, snap, groups = self._now(snap)
            if now is None:
                self._need_any(snap)
                raise NothingPlaying()
            cmd = action.split(".")[1]
            if now["source"] == "spotify":
                if cmd == "play" and now["playing"] or cmd == "pause" and not now["playing"]:
                    return
                await getattr(self.spotify, cmd)()
                before = (now["title"], now["playing"])
                await self._settle_spotify(lambda p: p and (((p.get("item") or {}).get("name"), p.get("is_playing"))
                                                            != before or cmd == "previous"))
                return
            if cmd == "play" and now["playing"] or cmd == "pause" and not now["playing"]:
                return
            await self._blocking(self.backend.media, uuid, cmd)
            title = now["title"]
            if cmd in ("play", "pause"):
                want = cmd == "play"
                await self._settle_cast(lambda: (self._now()[0] or {}).get("playing") == want)
            elif cmd == "next":
                await self._settle_cast(lambda: (self._now()[0] or {}).get("title") != title)
            return

        if action == "music.speakers":
            self._need_any(snap)
            now, uuid, snap, groups = self._now(snap)
            kind, target_uuid, names, label = self._target(a["speakers"], groups, snap)
            if now is not None and set(now["on"]) == set(a["speakers"]):
                return
            if self.spotify and self.spotify.linked and now is not None and now["source"] == "spotify" or (
                    now is None and self.spotify and self.spotify.linked and (self.spotify.player or {}).get("item")):
                dev = await self._spotify_device(names, label)
                await self.spotify.transfer(dev, play=True)
                want = set(a["speakers"])
                await self._settle_spotify(lambda p: p and set(self._spotify_target(
                    (p.get("device") or {}).get("name"), groups) or []) == want)
                return
            if now is None:
                raise NothingPlaying()
            raise NeedsSpotify("Moving music between speakers needs Spotify linked. Link it on the iMac, "
                               "or start the music on those speakers from your phone.")

        if action == "music.start":
            if not (self.spotify and self.spotify.linked):
                raise NeedsSpotify("Spotify is not linked yet. Link it on the iMac to start music from here.")
            self._need_any(snap)
            now, uuid, snap, groups = self._now(snap)
            if self.spotify_only:
                dev = await self._play_here()
            else:
                speakers = a.get("speakers") or (now["on"] if now else None) or ["lounge-room"]
                kind, target_uuid, names, label = self._target(speakers, groups, snap)
                dev = await self._spotify_device(names, label)
            what = a["what"]
            ctx, uris = None, None
            if what == "playlist":
                if "playlist" not in a:
                    raise Conflict("Pick a playlist to play.")
                ctx = "spotify:playlist:" + a["playlist"]
            elif what == "uri":
                if "uri" not in a:
                    raise Conflict("Pick something to play.")
                if a["uri"].startswith("spotify:track:"):
                    uris = [a["uri"]]
                else:
                    ctx = a["uri"]
            elif what in ("main", "discover"):
                lib = await self.spotify.library()
                if what == "main":
                    if not lib.get("main"):
                        raise Conflict("There is no main playlist yet. Pick one in the music view.")
                    ctx = "spotify:playlist:" + lib["main"]
                else:
                    if not lib.get("discover"):
                        raise Conflict("Spotify has not shown the hub your Discover Weekly yet. Play it once in the Spotify app, then try again.")
                    ctx = lib["discover"]
            else:
                last = self.spotify.quick.get("last") or {}
                if what == "recent" and (last.get("context_uri") or last.get("track_uri")):
                    if last.get("context_uri"):
                        ctx = last["context_uri"]
                    else:
                        uris = [last["track_uri"]]
                else:                                   # liked, or nothing recent: Liked Songs
                    ctx = await self.spotify.liked_context()
                    if not ctx:
                        uris = await self.spotify.liked_uris()
                        if not uris:
                            raise Conflict("There is nothing in Liked Songs to play yet. Pick a playlist.")
            await self.spotify.play(dev, context_uri=ctx, uris=uris)
            await self._settle_spotify(lambda p: p and p.get("is_playing") and (p.get("device") or {}).get("id") == dev)
            return

        if action == "music.search_play":
            if not (self.spotify and self.spotify.linked):
                raise NeedsSpotify("Spotify is not linked yet. Link it on the iMac to find music by name.")
            self._need_any(snap)
            now, uuid, snap, groups = self._now(snap)
            if not self.spotify_only:
                speakers = a.get("speakers") or (now["on"] if now else None) or ["lounge-room"]
                kind, target_uuid, names, label = self._target(speakers, groups, snap)
            res = await self.spotify.search(a["query"])
            pick = pick_result(a["query"], res)
            if not pick:
                raise Conflict(f"Spotify found nothing for \"{a['query']}\".")
            what, uri, name = pick
            dev = await self._play_here() if self.spotify_only else await self._spotify_device(names, label)
            if what == "track":
                await self.spotify.play(dev, uris=[uri])
            else:
                await self.spotify.play(dev, context_uri=uri)
            await self._settle_spotify(lambda p: p and p.get("is_playing") and (p.get("device") or {}).get("id") == dev)
            return
        raise Conflict("That is not something the speakers can do.")
