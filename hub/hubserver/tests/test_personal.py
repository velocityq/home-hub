"""Personal views: presence, the card (titles and times only), calendar sources and the connect command."""
import datetime as dt
import json
import os
import stat

from hubserver import config as cfgmod
from hubserver import personal as P
from hubserver.app import make_app

from .conftest import auth, build, close

PEOPLE = ["Sam", "Alex"]
TZ = dt.timezone(dt.timedelta(hours=11))
NOW = dt.datetime(2026, 11, 11, 9, 30, tzinfo=TZ)

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:1
DTSTART:20261111T150000
DTEND:20261111T160000
SUMMARY:Swim lesson
LOCATION:Secret pool address
DESCRIPTION:door code 1234
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART;VALUE=DATE:20261113
SUMMARY:Grandma visiting
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART:20261109T080000
DTEND:20261109T083000
RRULE:FREQ=DAILY;COUNT=10
SUMMARY:School run
END:VEVENT
BEGIN:VEVENT
UID:4
DTSTART:20261201T100000
SUMMARY:Too far away
END:VEVENT
BEGIN:VEVENT
UID:5
DTSTART:20261112T100000
STATUS:CANCELLED
SUMMARY:Cancelled thing
END:VEVENT
END:VCALENDAR
"""


def snapshot(tmp_path, events, fetched="2026-11-11T08:00:00+11:00"):
    p = tmp_path / "calendar.json"
    p.write_text(json.dumps({"fetched": fetched, "events": events}))
    return str(p)


async def test_card_titles_and_times_only(home, tmp_path):
    snap = snapshot(tmp_path, [
        {"title": "Team meeting", "start": "2026-11-12T09:30:00+11:00", "allDay": False,
         "link": "https://calendar/secret", "meet": "https://meet/abc"},
        {"title": "Yesterday", "start": "2026-11-10T09:30:00+11:00"},
        {"title": "Next month", "start": "2026-12-20T09:30:00+11:00"},
    ])
    cfg = {"people": PEOPLE, "personal": {"Sam": {"calendars": [{"name": "Work", "snapshot": snap}]}}}
    p = P.Personal(cfg, clock=lambda: NOW)
    card = await p.card("Sam")
    evs = card["calendar"]["events"]
    assert [e["title"] for e in evs] == ["Team meeting"]
    assert set(evs[0]) == {"title", "start", "allDay", "calendar"}          # no link, no meet, nothing else
    assert card["calendar"]["sources"] == [{"name": "Work", "connected": True, "note": None}]
    assert card["ring"]["connected"] is False and card["parcels"]["connected"] is False


async def test_snapshot_missing_or_stale(home, tmp_path):
    cfg = {"people": PEOPLE, "personal": {"Sam": {"calendars": [{"name": "Work", "snapshot": str(tmp_path / "nope.json")}]}}}
    card = await P.Personal(cfg, clock=lambda: NOW).card("Sam")
    assert card["calendar"]["sources"][0]["connected"] is False
    snap = snapshot(tmp_path, [], fetched="2026-11-09T08:00:00+11:00")
    cfg = {"people": PEOPLE, "personal": {"Sam": {"calendars": [{"name": "Work", "snapshot": snap}]}}}
    card = await P.Personal(cfg, clock=lambda: NOW).card("Sam")
    src = card["calendar"]["sources"][0]
    assert src["connected"] is True and src["note"].startswith("last updated")


async def test_ics_calendar_repeats_and_privacy(home):
    P.save_calendar_address("Alex", "Family", "webcal://example.com/private-abc/basic.ics")
    saved = cfgmod.read_json(cfgmod.path("personal.json"))
    assert saved["Alex"][0]["ics"].startswith("https://example.com/")
    assert stat.S_IMODE(os.stat(cfgmod.path("personal.json")).st_mode) == 0o600
    got = []

    async def fetch(url):
        got.append(url)
        return ICS
    p = P.Personal({"people": PEOPLE}, fetch=fetch, clock=lambda: NOW)
    card = await p.card("Alex")
    titles = [e["title"] for e in card["calendar"]["events"]]
    assert "Swim lesson" in titles and "Grandma visiting" in titles
    assert titles.count("School run") == 6          # 12 to 17 Nov: the repeat is expanded, the 11th already ended
    assert "Too far away" not in titles and "Cancelled thing" not in titles
    blob = json.dumps(card)
    assert "Secret pool" not in blob and "1234" not in blob and "example.com" not in blob
    assert card["calendar"]["sources"] == [{"name": "Family", "connected": True, "note": None}]
    await p.card("Alex")
    assert len(got) == 1                                                       # downloaded once, then reused
    assert P.remove_calendar("Alex", "Family") is True


async def test_ics_download_failure_says_so(home):
    P.save_calendar_address("Alex", "Family", "https://example.com/x.ics")

    async def fetch(url):
        raise OSError("down")
    card = await P.Personal({"people": PEOPLE}, fetch=fetch, clock=lambda: NOW).card("Alex")
    assert card["calendar"]["sources"][0]["connected"] is False
    assert card["calendar"]["events"] == []


def test_bad_calendar_address_refused(home):
    for bad in ("http://plain.example.com/x.ics", "my password", ""):
        try:
            P.save_calendar_address("Alex", "Family", bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    try:
        P.save_calendar_address("Bob", "Family", "https://example.com/x.ics", PEOPLE)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted an unknown person")


async def test_presence_and_card_routes(home, tmp_path):
    c = await build(home)
    try:
        snap = snapshot(tmp_path, [{"title": "Dentist", "start": (dt.datetime.now().astimezone() + dt.timedelta(hours=2)).isoformat()}])
        c.client.app["personal"].cfg["personal"] = {"Sam": {"calendars": [{"name": "Work", "snapshot": snap}]}}
        r = await c.client.post("/api/presence", json={"who": "Sam", "how": "face"})
        assert r.status == 401
        r = await c.client.post("/api/presence", json={"who": "Sam", "how": "face"}, headers=auth())
        body = await r.json()
        assert r.status == 200 and body["presence"]["who"] == "Sam" and body["presence"]["how"] == "face"
        for bad in ({"who": "Mallory", "how": "tap"}, {"who": "Sam", "how": "photo"}, ["x"]):
            r = await c.client.post("/api/presence", json=bad, headers=auth())
            assert r.status == 400
        r = await c.client.post("/api/presence", json={"who": None, "how": "face"}, headers=auth())
        assert (await r.json())["presence"]["who"] is None
        r = await c.client.get("/api/personal/Sam", headers=auth())
        card = (await r.json())["card"]
        assert [e["title"] for e in card["calendar"]["events"]] == ["Dentist"]
        r = await c.client.get("/api/personal/Sam")
        assert r.status == 401
        r = await c.client.get("/api/personal/Mallory", headers=auth())
        assert r.status == 404
    finally:
        await close(c)


def test_people_and_place_come_from_config_only():
    assert P.people_from({}) == [] and P.place_from({}) == ""
    cfg = {"people": ["Sam", "Alex", "Sam", "<b>x</b>", 7, "A" * 40, "Mary Jo", "O'Neil"], "place": "  Somewhere   nice "}
    assert P.people_from(cfg) == ["Sam", "Alex", "Mary Jo", "O'Neil"]
    assert P.place_from(cfg) == "Somewhere nice"
    assert P.people_from({"people": [f"P{chr(97 + i)}" for i in range(20)]})[-1] == "Ph"      # at most 8


async def test_no_people_means_no_cards(home):
    p = P.Personal({})
    assert p.people == []
    try:
        await p.card("Sam")
    except KeyError:
        pass
    else:
        raise AssertionError("a card for someone not in config")
    try:
        p.set_presence("Sam", "tap", "wall")
    except ValueError:
        pass
    else:
        raise AssertionError("presence for someone not in config")


async def test_home_route_gives_names_and_place(home):
    c = await build(home)
    try:
        r = await c.client.get("/api/home")
        assert r.status == 401
        r = await c.client.get("/api/home", headers=auth())
        body = await r.json()
        assert body == {"ok": True, "people": ["Sam", "Alex"], "place": "Riverside"}
    finally:
        await close(c)
