"""Cast discovery and control for the 3 ceiling speakers and their Google Home groups.

pychromecast works with threads. This module keeps everything thread side here: the browser and
the device connections call `notify()` (made thread safe by the caller) whenever something changes,
and `snapshot()` gives a plain dict the async side can read at any time.

Only these are ever connected to:
  - speakers whose mDNS model is the configured one (WiFiCeilingSpeakerV2) AND whose Cast name
    is in the speaker map (so a "Spare Bedroom" speaker of the same model is never touched);
  - Cast groups (to learn their members). A group is only listed when every member is one of
    the 3 speakers.
TVs and every other Cast device are ignored.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import time

log = logging.getLogger("hub.cast")

ACTIVE_STATES = ("PLAYING", "PAUSED", "BUFFERING")
GROUP_MODEL = "google cast group"


def _norm_uuid(u):
    from uuid import UUID
    try:
        return str(UUID(str(u)))
    except ValueError:
        return str(u)


def media_dict(ms):
    """A pychromecast MediaStatus as a plain dict, or None when there is no media."""
    if ms is None or ms.player_state in (None, "UNKNOWN", "IDLE") and not ms.title:
        return None
    try:
        pos = ms.adjusted_current_time
    except Exception:
        pos = ms.current_time
    art = None
    try:
        imgs = ms.images
        art = imgs[0].url if imgs else None
    except Exception:
        pass
    return {"title": ms.title, "artist": ms.artist or ms.album_artist, "album": ms.album_name, "art": art,
            "duration": int(ms.duration) if ms.duration else None,
            "position": int(pos) if isinstance(pos, (int, float)) else None,
            "state": ms.player_state,
            "can": {"pause": bool(ms.supports_pause), "next": bool(ms.supports_queue_next),
                    "previous": bool(ms.supports_queue_prev)}}


class _Listener:
    """Status, media and connection listener for one device."""

    def __init__(self, backend, uuid):
        self.b, self.uuid = backend, uuid

    def new_cast_status(self, status):
        self.b._changed()

    def new_media_status(self, status):
        self.b._changed()

    def load_media_failed(self, item, code):
        pass

    def new_connection_status(self, status):
        with self.b.lock:
            self.b.conn[self.uuid] = status.status
        self.b._changed()

    # multizone (groups)
    def multizone_member_added(self, uuid):
        self.b._changed()

    def multizone_member_removed(self, uuid):
        self.b._changed()

    def multizone_status_received(self):
        self.b._changed()

    def multizone_playback_session_updated(self, update):
        self.b._changed()


class RealCast:
    def __init__(self, cfg, notify=lambda: None):
        self.speaker_by_cast = {v["cast"].strip().lower(): sid for sid, v in cfg["speakers"].items()}
        self.model = (cfg.get("speaker_model") or "").lower()
        self.notify = notify
        self.lock = threading.RLock()
        self.casts = {}       # uuid str -> Chromecast
        self.kind = {}        # uuid str -> sid (speaker) or "group"
        self.names = {}       # uuid str -> friendly name
        self.mz = {}          # group uuid str -> MultizoneController
        self.conn = {}        # uuid str -> "CONNECTED" | "CONNECTING" | "LOST" | ...
        self.seen_other = {}  # friendly name -> model (ignored devices, for the report)
        self.zc = None
        self.browser = None
        self._stopped = False

    # ---------- life ----------
    def start(self):
        import zeroconf
        from pychromecast.discovery import CastBrowser, SimpleCastListener
        self.zc = zeroconf.Zeroconf()
        self.browser = CastBrowser(SimpleCastListener(self._add, self._remove, self._update), self.zc)
        self.browser.start_discovery()
        log.info("cast: discovery started")

    def stop(self):
        self._stopped = True
        try:
            if self.browser:
                self.browser.stop_discovery()
        except Exception:
            pass
        with self.lock:
            casts = list(self.casts.values())
            self.casts.clear()
        for cc in casts:
            try:
                cc.disconnect(timeout=3)
            except Exception:
                pass
        try:
            if self.zc:
                self.zc.close()
        except Exception:
            pass

    def _changed(self):
        try:
            self.notify()
        except Exception:
            pass

    # ---------- discovery (zeroconf thread) ----------
    def _add(self, uuid, service):
        self._consider(uuid)

    def _update(self, uuid, service):
        self._consider(uuid)

    def _remove(self, uuid, service, cast_info):
        u = str(uuid)
        with self.lock:
            cc = self.casts.pop(u, None)
            self.kind.pop(u, None)
            self.mz.pop(u, None)
            self.conn.pop(u, None)
        if cc:
            log.info("cast: %s went away", cast_info.friendly_name)
            threading.Thread(target=lambda: cc.disconnect(timeout=3), daemon=True).start()
        self._changed()

    def _consider(self, uuid):
        if self._stopped:
            return
        ci = self.browser.devices.get(uuid)
        if ci is None:
            return
        u = str(uuid)
        name = (ci.friendly_name or "").strip()
        model = (ci.model_name or "").lower()
        is_group = ci.cast_type == "group" or model == GROUP_MODEL or ci.port != 8009
        sid = self.speaker_by_cast.get(name.lower()) if model == self.model else None
        with self.lock:
            self.names[u] = name
            if u in self.casts:
                return
            if sid:
                kind, cast_type = sid, "audio"
            elif is_group:
                kind, cast_type = "group", "group"
            else:
                if name not in self.seen_other:
                    self.seen_other[name] = ci.model_name
                    log.info("cast: ignoring %r (%s)", name, ci.model_name)
                return
            self.kind[u] = kind
            self.casts[u] = None     # reserved while connecting
        threading.Thread(target=self._connect, args=(ci, kind, cast_type), daemon=True,
                         name=f"cast-connect-{name}").start()

    def _connect(self, ci, kind, cast_type):
        import pychromecast
        from pychromecast.controllers.multizone import MultizoneController
        u = str(ci.uuid)
        try:
            # Give the cast type up front: asking the speaker over HTTP times out on these speakers.
            info = dataclasses.replace(ci, cast_type=ci.cast_type or cast_type)
            cc = pychromecast.get_chromecast_from_cast_info(info, self.zc, tries=None, retry_wait=5, timeout=10)
            lst = _Listener(self, u)
            cc.register_status_listener(lst)
            cc.media_controller.register_status_listener(lst)
            cc.register_connection_listener(lst)
            mz = None
            if kind == "group":
                mz = MultizoneController(cc.uuid)
                mz.register_listener(lst)
                cc.register_handler(mz)
            with self.lock:
                if self._stopped or u not in self.kind:
                    return
                self.casts[u] = cc
                if mz:
                    self.mz[u] = mz
            cc.start()
            if mz:
                try:
                    cc.wait(timeout=15)
                    mz.update_members()
                except Exception:
                    pass
            log.info("cast: connected to %s (%s)", ci.friendly_name, "group" if kind == "group" else kind)
        except Exception as e:
            log.warning("cast: could not connect to %s: %s", ci.friendly_name, type(e).__name__)
            with self.lock:
                self.casts.pop(u, None)
                self.kind.pop(u, None)
        self._changed()

    # ---------- reading ----------
    def _uuid_to_sid(self):
        return {u: k for u, k in self.kind.items() if k != "group"}

    def snapshot(self):
        with self.lock:
            items = [(u, cc, self.kind.get(u), self.names.get(u), self.conn.get(u), self.mz.get(u))
                     for u, cc in self.casts.items()]
            u2s = self._uuid_to_sid()
        speakers, groups = {}, []
        for u, cc, kind, name, conn, mz in items:
            st = getattr(cc, "status", None) if cc else None
            ms = None
            if cc is not None:
                try:
                    ms = cc.media_controller.status
                except Exception:
                    ms = None
            app = st.display_name if st else None
            idle = cc.is_idle if cc is not None and st is not None else True
            row = {"uuid": u, "name": name, "connected": conn == "CONNECTED" and st is not None,
                   "volume": int(round(st.volume_level * 100)) if st and st.volume_level is not None else None,
                   "muted": bool(st.volume_muted) if st else None, "app": app, "idle": idle,
                   "media": media_dict(ms) if not idle else None}
            if kind == "group":
                members = []
                if mz is not None:
                    members = [_norm_uuid(m) for m in mz.members]
                row["members_uuid"] = members
                row["members"] = [u2s.get(m) for m in members]
                groups.append(row)
            elif kind:
                speakers[kind] = row
        return {"speakers": speakers, "groups": groups}

    # ---------- control (blocking; run in a worker thread) ----------
    def _cast(self, uuid):
        with self.lock:
            cc = self.casts.get(uuid)
        if cc is None:
            raise LookupError("not connected")
        return cc

    def set_volume(self, uuid, value):
        cc = self._cast(uuid)
        cc.set_volume(max(0, min(100, value)) / 100.0, timeout=8)
        end = time.time() + 3
        while time.time() < end:   # the status listener has the new level once the speaker says so
            st = cc.status
            if st and abs(st.volume_level * 100 - value) < 1.5:
                return
            time.sleep(0.1)

    def media(self, uuid, cmd):
        mc = self._cast(uuid).media_controller
        if cmd == "play":
            mc.play(timeout=8)
        elif cmd == "pause":
            mc.pause(timeout=8)
        elif cmd == "next":
            mc.queue_next(timeout=8)
        elif cmd == "previous":
            mc.queue_prev(timeout=8)
        else:
            raise ValueError(cmd)
