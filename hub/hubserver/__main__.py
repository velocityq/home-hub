"""Run the home hub.

    cd hub && .venv/bin/python -m hubserver [--port N] [--host H]
    cd hub && .venv/bin/python -m hubserver pair      one-time 6 digit pairing code, good for 10 minutes
    cd hub && .venv/bin/python -m hubserver clients   list the clients that have a key
    cd hub && .venv/bin/python -m hubserver revoke NAME   remove a client's key (a lost phone)
    cd hub && .venv/bin/python -m hubserver calendar NAME [--label Family]
          connect a private calendar address (iCal) to that person's wall card; it is read
          without showing it and saved in ~/.home-hub/personal.json (mode 600). --remove LABEL undoes it.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from aiohttp import web

from . import config as cfgmod

log = logging.getLogger("hub")


def build(cfg, keys=None):
    """The real hub with the real device adapters."""
    from .aircon import Aircon
    from .app import make_app
    from .cast_backend import RealCast
    from .hub import Hub
    from .speakers import Speakers
    from .spotify import Spotify
    from .tvs import Tvs

    holder = {}

    def changed():
        h = holder.get("hub")
        if h:
            h.changed()

    def changed_threadsafe():
        h = holder.get("hub")
        if h:
            h.changed_threadsafe()

    spotify = Spotify(cfg, on_change=changed)
    aircon = Aircon(cfg, on_change=changed, remember=cfgmod.remember, recall=cfgmod.recall)
    speakers = Speakers(cfg, on_change=changed, backend=RealCast(cfg, notify=changed_threadsafe), spotify=spotify)
    tvs = Tvs(cfg, on_change=changed)
    hub = Hub(cfg, aircon, speakers, tvs, spotify)
    holder["hub"] = hub
    return make_app(hub, keys or cfgmod.Keys(), cfg)


def _lan_address():
    """This Mac's address on the home network, for the tablet to type. No packet is sent: connecting a UDP
    socket only picks the outgoing interface. None when there is no network."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
        return ip if not ip.startswith("127.") else None
    except OSError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m hubserver", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "pair", "clients", "revoke", "calendar"])
    ap.add_argument("name", nargs="?", help="with revoke: the client to remove (see `clients`); with calendar: a name from \"people\" in config.json")
    ap.add_argument("--label", default="Calendar", help="with calendar: the name shown on the card (default Calendar)")
    ap.add_argument("--remove", metavar="LABEL", help="with calendar: remove that calendar from the card")
    ap.add_argument("--port", type=int, help="port (default from config.json, 8790)")
    ap.add_argument("--host", help="address to listen on (default 0.0.0.0)")
    a = ap.parse_args(argv)

    if a.command == "clients":
        cfgmod.ensure_home()
        names = cfgmod.Keys().names()
        print("Clients with a key: " + (", ".join(names) if names else "none"))
        return
    if a.command == "revoke":
        if not a.name:
            ap.error("say which client, for example: revoke phone-sam")
        cfgmod.ensure_home()
        if cfgmod.Keys().revoke(a.name):
            print(f"Removed {a.name}. Its key stops working straight away.")
        else:
            print(f"There is no client called {a.name}. Run `clients` to see the names.")
        return

    if a.command == "calendar":
        from . import personal
        people = personal.people_from(cfgmod.load_config())
        if a.name not in people:
            ap.error("say whose calendar: one of the names in \"people\" in ~/.home-hub/config.json ("
                     + (", ".join(people) or "none set yet") + "), for example: calendar Sam --label Family")
        if a.remove:
            done = personal.remove_calendar(a.name, a.remove)
            print(f"Removed {a.remove} from {a.name}'s card." if done else f"{a.name} has no calendar called {a.remove}.")
            return
        import getpass
        url = getpass.getpass(f"Paste {a.name}'s private calendar address, then press Return (it will not show): ")
        try:
            personal.save_calendar_address(a.name, a.label, url, people)
        except ValueError as e:
            print(f"Not saved: {e}.")
            return
        print(f"Saved. {a.name}'s card on the wall now shows {a.label} (event titles and times only).")
        return

    if a.command == "pair":
        cfgmod.ensure_home()
        code = cfgmod.new_pair_code()
        print(f"Pairing code: {code}")
        addr = _lan_address()
        if addr:
            port = a.port or cfgmod.load_config().get("port", 8790)
            print(f"Hub address:  {addr}" + ("" if port == 8790 else f":{port}"))
            print("On the wall tablet's first screen, type the address and the code, then tap Connect.")
        print("It works once, for 10 minutes. Other devices send it to POST /api/pair "
              "with a name, for example {\"code\": \"%s\", \"name\": \"phone-sam\"}." % code)
        return

    cfgmod.setup_logging(to_file=True)
    cfg = cfgmod.load_config()
    keys = cfgmod.Keys()
    port = a.port or int(cfg.get("port") or 8790)
    host = a.host or cfg.get("host") or "0.0.0.0"
    log.info("hub starting on %s:%s (clients: %s)", host, port, ", ".join(keys.names()))
    from .app import AccessLogger
    app = build(cfg, keys)
    web.run_app(app, host=host, port=port, access_log=logging.getLogger("hub.access"),
                access_log_class=AccessLogger, print=lambda *_: log.info("hub listening on http://%s:%s", host, port),
                handle_signals=True, shutdown_timeout=5)


if __name__ == "__main__":
    main()
