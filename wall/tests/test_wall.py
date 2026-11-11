"""Browser tests for the wall screen against the fake hub (hub/fake_hub.py).

    cd ~/home-hub && hub/.venv/bin/python -m pytest wall/tests -q

Every test checks that the page logged no console errors (except the failed requests a test causes on purpose).
"""
import json
import re
import time
from datetime import datetime

import pytest

from conftest import BASE, KEY, patch_state

NET = r"Failed to load resource|ERR_CONNECTION_REFUSED|WebSocket connection to"


# ---------------------------------------------------------------- keys

def test_no_key_shows_the_key_panel(make_wall):
    w = make_wall()
    w.open(key=False)
    w.page.wait_for_selector(".keypanel")
    assert "This screen needs its hub key" in w.page.inner_text(".keypanel")
    w.shot("10-no-key")
    # paste the key on the screen itself
    w.page.fill("#keyText", KEY)
    w.page.click(".keypanel button[type=submit]")
    w.ready()
    assert w.page.locator(".keypanel").count() == 0
    assert w.page.evaluate("localStorage.getItem('hub.key')") == KEY


def test_wrong_key_shows_the_panel(make_wall):
    w = make_wall()
    w.allow(r"status of 401")
    w.page.goto(BASE + "/#key=wrong")
    w.page.wait_for_selector(".keypanel")
    assert "did not work" in w.page.inner_text(".keypanel")


def test_key_from_the_address_is_kept_and_hidden(make_wall):
    w = make_wall().open()
    assert w.page.evaluate("location.hash") == ""
    assert w.page.evaluate("localStorage.getItem('hub.key')") == KEY
    w.page.goto(BASE + "/")            # no key in the address now
    w.ready()
    assert w.page.locator('[data-card="aircon"]').count() == 1


def test_a_401_on_an_action_shows_the_panel(make_wall):
    w = make_wall().open()
    w.allow(r"status of 401")
    w.page.route(re.compile(r".*/api/action$"), lambda r: r.fulfill(status=401, content_type="application/json",
                                                                    body='{"ok": false, "error": "This needs the hub key."}'))
    w.page.click('[data-do="nudge"][data-arg="1"]')
    w.page.wait_for_selector(".keypanel")


# ---------------------------------------------------------------- every control sends the right action

def test_layout_a_controls(make_wall):
    w = make_wall("a").open()
    p = w.page
    w.shot("01-home-a-mountain")
    w.expect(lambda: p.click('[data-card="aircon"] [data-do="acPower"]'), "aircon.power", {"on": False})
    w.expect(lambda: p.click('[data-card="aircon"] [data-do="acPower"]'), "aircon.power", {"on": True})
    w.expect(lambda: p.click('[data-card="aircon"] [data-do="nudge"][data-arg="1"]'), "aircon.nudge", {"delta": 1})
    assert p.inner_text('[data-card="aircon"] [data-set]') == "23°"
    w.expect(lambda: p.click('[data-card="aircon"] [data-do="nudge"][data-arg="-1"]'), "aircon.nudge", {"delta": -1})
    w.expect(lambda: p.click('[data-card="music"] [data-do="playPause"]'), "music.pause", {})
    w.expect(lambda: p.click('[data-card="music"] [data-do="playPause"]'), "music.play", {})
    w.expect(lambda: p.click('[data-card="music"] [data-do="next"]'), "music.next", {})
    assert "Holocene" in p.inner_text('[data-card="music"]')


def test_aircon_sheet_controls(make_wall):
    w = make_wall("a").open()
    p = w.page
    w.sheet("aircon")
    w.shot("02-sheet-aircon")
    w.expect(lambda: p.click('.sheet [data-do="setTemp"][data-arg="1"]'), "aircon.set_temp", {"value": 23})
    w.expect(lambda: p.click('.sheet [data-do="setTemp"][data-arg="-1"]'), "aircon.set_temp", {"value": 22})
    for m in ["heat", "fan", "dry", "auto", "cool"]:
        w.expect(lambda: p.click(f'.sheet [data-do="acMode"][data-arg="{m}"]'), "aircon.mode", {"mode": m})
    fans = p.eval_on_selector_all('.sheet [data-do="acFan"]', "els => els.map(e => e.dataset.arg)")
    assert fans == w.hub.state()["aircon"]["fan_speeds"]
    for f in fans:
        w.expect(lambda: p.click(f'.sheet [data-do="acFan"][data-arg="{f}"]'), "aircon.fan", {"speed": f})
    w.expect(lambda: p.click('.sheet [data-do="zone"][data-arg="living"]'), "aircon.zone", {"zone": "living", "on": True})
    assert "on" in p.get_attribute('.sheet [data-do="zone"][data-arg="living"]', "class")
    w.expect(lambda: p.click('.sheet [data-do="zone"][data-arg="media"]'), "aircon.zone", {"zone": "media", "on": False})
    w.expect(lambda: p.click('.sheet [data-do="zonesAll"][data-arg="on"]'), "aircon.zones_all", {"on": True})
    assert "7 of 7 on" in p.inner_text(".sheet")
    w.expect(lambda: p.click('.sheet [data-do="zonesAll"][data-arg="off"]'), "aircon.zones_all", {"on": False})
    w.expect(lambda: p.click('.sheet [data-do="acPower"]'), "aircon.power", {"on": False})
    w.close()


def test_only_the_fan_speeds_the_unit_has(make_wall):
    w = make_wall("a")
    patch_state(w.page, lambda s: s["aircon"].update(fan_speeds=["auto", "quiet", "turbo"], fan="quiet"))
    w.open()
    w.sheet("aircon")
    assert w.page.eval_on_selector_all('.sheet [data-do="acFan"]', "els => els.map(e => e.innerText)") == ["Auto", "Quiet", "Turbo"]


def test_music_sheet_controls(make_wall):
    w = make_wall("a").open()
    p = w.page
    # all four Google Home groups exist here, so any mix of speakers is allowed
    w.hub.call("POST", "/fake/groups", {"groups": [{"members": m} for m in (
        ["lounge-room", "theatre"], ["lounge-room", "outside"], ["theatre", "outside"],
        ["lounge-room", "theatre", "outside"])]})
    w.sheet("music")
    w.shot("03-sheet-music")
    w.expect(lambda: p.click('.sheet [data-do="prev"]'), "music.previous", {})
    w.expect(lambda: p.click('.sheet [data-do="playPause"]'), "music.pause", {})
    w.expect(lambda: p.click('.sheet [data-do="playPause"]'), "music.play", {})
    w.expect(lambda: p.click('.sheet [data-do="next"]'), "music.next", {})
    # tick Theatre: all three speakers, in the hub's order
    w.expect(lambda: p.click('.sheet button.tick[data-arg="theatre"]'), "music.speakers",
             {"speakers": ["lounge-room", "theatre", "outside"]})
    # untick Outside by tapping its name
    w.expect(lambda: p.click('.sheet .spk[data-spk="outside"] button[data-do="spkGroup"]:not(.tick)'), "music.speakers",
             {"speakers": ["lounge-room", "theatre"]})
    # drag a speaker's volume with the mouse
    box = p.locator('.sheet input[data-vol="theatre"]').bounding_box()
    got = w.expect(lambda: p.mouse.click(box["x"] + box["width"] * 0.8, box["y"] + box["height"] / 2), "speakers.volume")
    assert got["args"]["speaker"] == "theatre" and 70 <= got["args"]["value"] <= 90
    w.expect(lambda: p.eval_on_selector('.sheet input[data-vol="all"]',
             "e => { e.value = 30; e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true})); }"),
             "speakers.volume", {"speaker": "all", "value": 30})
    w.close()


def test_last_speaker_cannot_be_unticked(make_wall):
    w = make_wall("a")
    patch_state(w.page, lambda s: s["speakers"]["now"].update(on=["outside"]))
    w.open()
    w.sheet("music")
    before = len(w.hub.log())
    w.page.click('.sheet button.tick[data-arg="outside"]')
    assert "at least one speaker" in w.toast()
    assert len(w.hub.log()) == before


def test_tv_sheet_controls(make_wall):
    w = make_wall("a").open()
    p = w.page
    w.sheet("tvs")
    w.shot("04-sheet-tvs")
    lr = '.sheet [data-tvcard="living-room"]'
    w.expect(lambda: p.click(f'{lr} [data-do="tvVol"][data-arg="1"]'), "tv.volume", {"tv": "living-room", "delta": 1})
    assert "Volume 19" in p.inner_text(lr)
    w.expect(lambda: p.click(f'{lr} [data-do="tvVol"][data-arg="-1"]'), "tv.volume", {"tv": "living-room", "delta": -1})
    w.expect(lambda: p.click(f'{lr} [data-do="tvMute"]'), "tv.mute", {"tv": "living-room", "muted": True})
    assert "Muted" in p.inner_text(lr)
    w.expect(lambda: p.click(f'{lr} [data-do="tvMute"]'), "tv.mute", {"tv": "living-room", "muted": False})
    apps = w.hub.state()["tvs"]["apps"]
    assert p.eval_on_selector_all(f'{lr} [data-do="tvApp"]', "els => els.map(e => e.dataset.arg)") == apps
    w.expect(lambda: p.click(f'{lr} [data-do="tvApp"][data-arg="Netflix"]'), "tv.launch", {"tv": "living-room", "app": "Netflix"})
    w.expect(lambda: p.click(f'{lr} [data-do="tvPower"]'), "tv.power", {"tv": "living-room", "on": False})
    w.expect(lambda: p.click('.sheet [data-tvcard="bedroom"] [data-do="tvPower"]'), "tv.power", {"tv": "bedroom", "on": True})
    w.expect(lambda: p.click('.sheet [data-tvcard="frame"] [data-do="frameArt"]'), "tv.art_mode", {"tv": "frame", "on": False})
    assert p.locator('.sheet [data-tvcard="bedroom"] .screen.on').count() == 1
    w.close()


def test_layout_b_controls(make_wall):
    w = make_wall("b").open()
    p = w.page
    w.shot("05-home-b-mountain")
    w.expect(lambda: p.click('[data-card="aircon"] [data-do="acMode"][data-arg="heat"]'), "aircon.mode", {"mode": "heat"})
    w.expect(lambda: p.click('[data-card="aircon"] [data-do="nudge"][data-arg="1"]'), "aircon.nudge", {"delta": 1})
    w.expect(lambda: p.click('[data-card="aircon"] [data-do="acPower"]'), "aircon.power", {"on": False})
    w.expect(lambda: p.click('[data-card="music"] [data-do="playPause"]'), "music.pause", {})
    w.expect(lambda: p.click('[data-card="music"] [data-do="next"]'), "music.next", {})
    w.expect(lambda: p.click('[data-card="tvs"] [data-do="tvPower"][data-tv="bedroom"]'), "tv.power", {"tv": "bedroom", "on": True})


def test_layout_c_controls(make_wall):
    w = make_wall("c", "night").open()
    p = w.page
    w.shot("06-home-c-night")
    w.expect(lambda: p.click('#ui [data-do="zone"][data-arg="rumpus"]'), "aircon.zone", {"zone": "rumpus", "on": True})
    w.expect(lambda: p.click('#ui [data-do="nudge"][data-arg="-1"]'), "aircon.nudge", {"delta": -1})
    w.expect(lambda: p.click('#ui [data-do="playPause"]'), "music.pause", {})
    w.expect(lambda: p.click('#ui [data-do="tvPower"][data-tv="frame"]'), "tv.power", {"tv": "frame", "on": True})
    w.sheet("aircon", src="c-pill-aircon")
    w.close()
    w.sheet("music", src="c-spk-theatre")
    w.close()


# ---------------------------------------------------------------- live updates

def test_live_update_reaches_a_second_screen(make_wall):
    w1 = make_wall("a").open()
    w2 = make_wall("c").open()
    w1.expect(lambda: w1.page.click('[data-card="aircon"] [data-do="nudge"][data-arg="1"]'), "aircon.nudge")
    w2.page.wait_for_function("document.querySelector('[data-src=\"c-pill-aircon\"]').innerText.includes('23°')", timeout=3000)
    # a change from somewhere else (Claude, the phone) shows on both
    w1.hub.call("POST", "/api/action", {"action": "aircon.zone", "args": {"zone": "bed-4", "on": True}}, key=KEY)
    w2.page.wait_for_function("document.querySelector('[data-do=\"zone\"][data-arg=\"bed-4\"]').classList.contains('on')", timeout=3000)
    w1.page.wait_for_function("document.querySelector('[data-card=\"aircon\"]').innerText.includes('4 of 7')", timeout=3000)


def test_spotify_link_shows_live(make_wall):
    w = make_wall("a").open()
    w.sheet("music")
    assert "Spotify is not linked yet" in w.page.inner_text(".sheet")
    w.hub.call("POST", "/fake/spotify", {"linked": True})
    w.page.wait_for_function("!document.querySelector('.sheet').innerText.includes('Spotify is not linked')", timeout=3000)
    w.hub.call("POST", "/fake/spotify", {"linked": False})


# ---------------------------------------------------------------- sheets open and close

@pytest.mark.parametrize("layout", ["a", "b", "c"])
def test_every_sheet_opens_and_closes(make_wall, layout):
    w = make_wall(layout).open()
    p = w.page
    for name in ["aircon", "music", "tvs", "settings", "ask"]:
        w.sheet(name)
        assert p.locator(".stage.sheet-open").count() == 1
        w.close()
        assert p.locator(".stage.sheet-open").count() == 0
        assert p.locator(".sheet").count() == 0
    # tap outside to close, and Esc
    w.sheet("aircon")
    p.mouse.click(10, 790)
    p.wait_for_selector(".sheet", state="detached")
    w.sheet("tvs")
    p.keyboard.press("Escape")
    p.wait_for_selector(".sheet", state="detached")
    p.wait_for_timeout(150)
    hidden = p.eval_on_selector_all("#ui [data-src]", "els => els.filter(e => e.style.visibility === 'hidden').length")
    assert hidden == 0


# ---------------------------------------------------------------- settings: 3 layouts x 2 scenes

def test_settings_switch_every_layout_and_scene(make_wall):
    w = make_wall("a").open()
    p = w.page
    w.sheet("settings")
    w.shot("07-sheet-settings")
    w.close()
    for scene in ["mountain", "night"]:
        for layout in ["a", "b", "c"]:
            w.sheet("settings")
            p.click(f'.sheet [data-action="setLayout"][data-arg="{layout}"]')
            p.click(f'.sheet [data-action="setScene"][data-arg="{scene}"]')
            assert p.locator(f'.sheet [data-action="setLayout"][data-arg="{layout}"].sel').count() == 1
            w.close()
            assert p.get_attribute("#stage", "data-layout") == layout
            assert p.get_attribute("#stage", "data-scene") == scene
            assert f"scenes/{scene}/photo.jpg" in p.inner_html("#scene")
            assert json.loads(p.evaluate("localStorage.getItem('hub.look')")) == {"layout": layout, "scene": scene}
            assert p.locator("#mic").is_visible() and p.locator('[data-open="ask"]').is_visible()
            assert p.inner_text("#note").strip() == ""
            p.wait_for_function("Array.from(document.images).every(i => i.complete)")
            p.wait_for_timeout(200)
            w.shot(f"08-look-{layout}-{scene}")
    p.reload()
    w.ready()
    assert p.get_attribute("#stage", "data-layout") == "c" and p.get_attribute("#stage", "data-scene") == "night"


# ---------------------------------------------------------------- touch targets

TARGETS_JS = """() => {
  const bad = [];
  const sel = '#ui button, #ui [data-do], #ui [data-open], #ui [data-action], .sheet .full button, .sheet .full [data-do], .sheet .full input, .sheet .close';
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('.mini')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === 'hidden') continue;
    let w = r.width, h = r.height;
    for (const ps of ['::before', '::after']) {
      const s = getComputedStyle(el, ps);
      if (s.content === 'none' || s.position !== 'absolute') continue;
      const o = (v) => Math.max(0, -parseFloat(v) || 0);
      w = Math.max(w, r.width + o(s.left) + o(s.right)); h = Math.max(h, r.height + o(s.top) + o(s.bottom));
    }
    if (w < 55.5 || h < 55.5) bad.push(`${el.className || el.tagName} ${el.dataset.do || el.dataset.action || el.dataset.open || ''} ${Math.round(w)}x${Math.round(h)}`);
  }
  return bad;
}"""


@pytest.mark.parametrize("layout", ["a", "b", "c"])
def test_touch_targets_are_56px(make_wall, layout):
    w = make_wall(layout).open()
    assert w.page.evaluate(TARGETS_JS) == []
    for name in ["aircon", "music", "tvs", "settings", "ask"]:
        w.sheet(name)
        assert w.page.evaluate(TARGETS_JS) == [], name
        w.close()


# ---------------------------------------------------------------- hub offline and back

def test_offline_banner_and_recovery(make_wall, hub):
    w = make_wall("a").open()
    w.allow(NET)
    p = w.page
    hub.stop()
    try:
        p.wait_for_selector(".banner.show", timeout=6000)
        assert "Can't reach the hub" in p.inner_text(".banner")
        assert p.eval_on_selector('[data-do="nudge"]', "e => getComputedStyle(e).pointerEvents") == "none"
        assert p.eval_on_selector("#mic", "e => getComputedStyle(e).pointerEvents") == "none"
        # the last known state stays on screen
        assert "22°" in p.inner_text('[data-card="aircon"]')
        w.shot("11-offline")
    finally:
        hub.start()
    p.wait_for_function("window.__wall.conn === 'online'", timeout=20000)
    p.wait_for_selector(".banner.show", state="detached", timeout=3000)
    assert p.eval_on_selector('[data-do="nudge"]', "e => getComputedStyle(e).pointerEvents") != "none"
    w.expect(lambda: p.click('[data-card="aircon"] [data-do="nudge"][data-arg="1"]'), "aircon.nudge", {"delta": 1})


# ---------------------------------------------------------------- devices not answering (/fake/fail)

@pytest.mark.parametrize("layout", ["a", "b", "c"])
def test_device_groups_not_answering(make_wall, hub, layout):
    w = make_wall(layout).open()
    p = w.page
    try:
        for dev, text in [("aircon", "Aircon not answering"), ("speakers", "Speakers not answering"), ("tvs", "TVs not answering")]:
            hub.fail(dev, True)
            p.wait_for_function(f"document.querySelector('#ui').innerText.includes({json.dumps(text)})", timeout=3000)
        if layout == "a":
            w.shot("12-not-answering")
        assert p.locator("#ui [data-do]").count() == 0
        hub.fail("aircon", False)
        p.wait_for_function("!document.querySelector('#ui').innerText.includes('Aircon not answering')", timeout=3000)
        assert p.locator('#ui [data-do="nudge"]').count() > 0
    finally:
        for dev in ("aircon", "speakers", "tvs"):
            hub.fail(dev, False)


def test_device_fails_while_sheet_open_rolls_back(make_wall, hub):
    w = make_wall("a").open()
    w.allow(r"status of 503")
    p = w.page
    w.sheet("aircon")
    # the hub answers 503 before its broadcast reaches the screen
    p.route(re.compile(r".*/api/action$"), lambda r: r.fulfill(status=503, content_type="application/json",
            body=json.dumps({"ok": False, "error": "The aircon is not answering.", "device": "aircon"})))
    p.click('.sheet [data-do="setTemp"][data-arg="1"]')
    assert w.toast() == "The aircon is not answering."
    w.idle()
    assert p.inner_text(".sheet [data-set]") == "22°"
    w.shot("13-toast-error")


# ---------------------------------------------------------------- 409 messages

def test_409_spotify_message(make_wall):
    w = make_wall("a").open()
    w.allow(r"status of 409")
    w.page.route(re.compile(r".*/api/action$"), lambda r: r.fulfill(status=409, content_type="application/json",
                 body=json.dumps({"ok": False, "error": "Spotify is not linked yet.", "needs": "spotify"})))
    w.page.click('[data-card="music"] [data-do="next"]')
    assert w.toast() == "Link Spotify on the iMac to do this"


def test_409_speaker_group_missing(make_wall):
    w = make_wall("a").open()
    w.allow(r"status of 409")
    p = w.page
    w.sheet("music")
    msg = "There is no Google Home group for Lounge Room + Theatre + Outside yet. Make it in the Google Home app."
    p.route(re.compile(r".*/api/action$"), lambda r: r.fulfill(status=409, content_type="application/json",
            body=json.dumps({"ok": False, "error": msg})))
    p.click('.sheet button.tick[data-arg="theatre"]')
    assert w.toast() == msg
    w.idle()
    assert "on" not in p.get_attribute('.sheet button.tick[data-arg="theatre"] .check', "class")
    w.shot("14-toast-409-group")


def test_409_tv_off_from_the_real_fake(make_wall, hub):
    # the screen thinks the TV is on; the hub knows better
    w = make_wall("a")
    w.allow(r"status of 409")
    patch_state(w.page, lambda s: s["tvs"]["devices"][1].update(power="on", app="Netflix", volume=10, muted=False))
    w.open()
    w.sheet("tvs")
    w.page.click('.sheet [data-tvcard="bedroom"] [data-do="tvVol"][data-arg="1"]')
    assert w.toast() == "The Bedroom TV is off. Turn it on first."


# ---------------------------------------------------------------- states that come from the hub

def test_nothing_playing(make_wall):
    w = make_wall("a")
    patch_state(w.page, lambda s: s["speakers"].update(now=None))
    w.open()
    card = w.page.inner_text('[data-card="music"]')
    assert "Nothing playing" in card and "Start Spotify on a phone" in card
    assert w.page.locator('[data-card="music"] [data-do]').count() == 0
    w.shot("15-nothing-playing")
    w.sheet("music")
    assert "Nothing playing" in w.page.inner_text(".sheet")
    assert w.page.locator(".sheet button.tick").count() == 0
    w.expect(lambda: w.page.eval_on_selector('.sheet input[data-vol="outside"]',
             "e => { e.value = 20; e.dispatchEvent(new Event('change', {bubbles: true})); }"), "speakers.volume", {"speaker": "outside", "value": 20})
    w.shot("16-sheet-music-nothing-playing")


def test_tv_waking_and_frame_art_mode(make_wall):
    w = make_wall("a")
    patch_state(w.page, lambda s: s["tvs"]["devices"][1].update(waking=True))
    w.open()
    assert "Waking" in w.page.inner_text('[data-card="tvs"]')
    assert "Art mode" in w.page.inner_text('[data-card="tvs"]')
    w.sheet("tvs")
    assert "Waking up" in w.page.inner_text('.sheet [data-tvcard="bedroom"] .screen')
    assert w.page.inner_text('.sheet [data-tvcard="frame"] .screen') == "Art mode"
    assert "on" in w.page.get_attribute('.sheet [data-tvcard="frame"] .sw', "class")
    w.shot("17-tv-waking-art")


def test_missing_parts_are_hidden(make_wall):
    w = make_wall("c")
    patch_state(w.page, lambda s: s.pop("tvs"))
    w.open()
    assert w.page.locator('[data-open="tvs"]').count() == 0
    assert w.page.locator('[data-do="tvPower"]').count() == 0
    assert w.page.locator('[data-open="aircon"]').count() > 0


def presences(hub):
    return [(e["presence"], e["how"]) for e in hub.log() if "presence" in e]


def test_name_tap_opens_the_personal_view(make_wall, hub):
    w = make_wall("a").open()
    p = w.page
    w.sheet("person", src="p-Sam")
    p.wait_for_selector('.sheet[data-sheet="person"] .me-ev')
    txt = p.inner_text(".sheet")
    assert "Sam" in txt and "Team meeting" in txt and "Your own view" in txt
    assert "Ring doorbell" in txt and "Parcels" in txt and txt.count("Not connected yet") == 2
    assert "Face ID works on the wall tablet." in txt                       # a desktop browser has no Face ID
    assert ("Sam", "tap") in presences(hub)
    w.shot("24-person-sam")
    p.click('.sheet [data-action="person"][data-arg="Alex"]')              # "I'm Alex"
    p.wait_for_selector('.sheet >> text=No calendar connected yet')
    assert "Alex" in p.inner_text(".sheet h2")
    w.close()
    assert presences(hub)[-1] == (None, "tap")


def test_tapped_view_goes_back_after_60_s(make_wall, hub):
    skew = "window.__skew = 0; const _now = Date.now; Date.now = () => _now() + window.__skew;"
    w = make_wall("a", init=skew).open()
    p = w.page
    w.sheet("person", src="p-Alex")
    p.wait_for_timeout(5500)
    assert p.locator('.sheet[data-sheet="person"]').count() == 1           # still open: touched 6 s ago
    p.evaluate("window.__skew = 61000")                                     # now the last touch was over 60 s ago
    p.wait_for_selector(".sheet", state="detached", timeout=7000)
    assert presences(hub)[-1] == (None, "tap")


FACE_APP = """
window.__face = { enrol: [], forget: [], cancel: 0 };
window.HubAndroid = {
  version: () => "1", openAirTouch: () => {}, startRecording: () => "denied", stopRecording: () => {}, cancelRecording: () => {},
  faceStatus: () => JSON.stringify({ type: "status", camera: "on", enrolled: [], who: null, rotationKnown: false }),
  faceEnrol: (n) => { window.__face.enrol.push(n); return "ok"; },
  faceForget: (n) => { window.__face.forget.push(n); },
  faceCancel: () => { window.__face.cancel++; },
};
"""


def face(p, **e):
    p.evaluate("e => window.__hubFace(e)", e)


def test_face_id_greets_sets_up_and_forgets(make_wall, hub):
    w = make_wall("a", init=FACE_APP).open()
    p = w.page
    face(p, type="who", who="Alex", how="face")                           # recognised: the view opens by itself
    p.wait_for_selector('.sheet[data-sheet="person"]')
    p.wait_for_timeout(650)
    assert "Alex" in p.inner_text(".sheet h2") and "Recognised by Face ID" in p.inner_text(".sheet")
    assert ("Alex", "face") in presences(hub)
    assert "No photo is taken or kept" in p.inner_text(".sheet")
    p.click('.sheet [data-action="faceEnrol"][data-arg="Alex"]')
    assert p.evaluate("window.__face.enrol") == ["Alex"]
    for got in range(0, 9, 2):
        face(p, type="enrol", name="Alex", state="progress", got=got, need=8)
    assert "Look at the screen and keep still" in p.inner_text(".sheet")
    w.shot("25-person-face-setup")
    face(p, type="enrol", name="Alex", state="done", got=8, need=8)
    p.wait_for_selector('.sheet >> text=Face ID is on for Alex')
    assert "Face ID is set up for Alex" in w.toast()
    p.click('.sheet [data-action="faceForget"][data-arg="Alex"]')         # first tap only arms it
    assert p.evaluate("window.__face.forget") == []
    p.wait_for_selector('.sheet >> text=Tap again to forget')
    p.click('.sheet [data-action="faceForget"][data-arg="Alex"]')
    assert p.evaluate("window.__face.forget") == ["Alex"]
    face(p, type="forgot", name="Alex")
    p.wait_for_selector('.sheet >> text=Set up face for Alex')
    w.close()


def test_face_view_closes_when_nobody_is_there(make_wall, hub):
    w = make_wall("a", init=FACE_APP).open()
    p = w.page
    face(p, type="who", who="Sam", how="face")
    p.wait_for_selector('.sheet[data-sheet="person"]')
    p.wait_for_timeout(700)
    face(p, type="who", who=None, how="face")
    p.wait_for_selector(".sheet", state="detached", timeout=13000)           # 10 s after Face ID stops seeing him
    assert presences(hub)[-1] == (None, "face")
    face(p, type="who", who="Sam", how="face")                           # a sheet in use is never covered
    p.wait_for_selector('.sheet[data-sheet="person"]')
    w.close()
    w.sheet("aircon")
    face(p, type="who", who="Alex", how="face")
    p.wait_for_timeout(300)
    assert p.locator('.sheet[data-sheet="person"]').count() == 0


def test_face_id_off_when_the_camera_is_gone(make_wall):
    w = make_wall("a", init=FACE_APP.replace('camera: "on"', 'camera: "none"')).open()
    p = w.page
    w.sheet("person", src="p-Sam")
    assert "Face ID is off" in p.inner_text(".sheet") and "Tapping your name still works" in p.inner_text(".sheet")
    w.shot("26-person-camera-off")
    w.close()


# ---------------------------------------------------------------- tap to talk

def hold(p, ms, sel="#mic"):
    box = p.locator(sel).bounding_box()
    p.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    p.mouse.down()
    p.wait_for_timeout(ms)


@pytest.mark.parametrize("layout", ["a", "b", "c"])
def test_hold_to_talk_sends_audio_and_shows_the_answer(make_wall, layout):
    w = make_wall(layout).open()
    p = w.page
    sent = []
    p.on("request", lambda r: sent.append((r.url, r.headers.get("content-type"))) if "/api/ask/audio" in r.url else None)
    hold(p, 1400)
    assert "listening" in p.get_attribute("#mic", "class")
    assert "Listening" in p.inner_text("#tip")
    if layout == "a":
        w.shot("18-listening")
    p.mouse.up()
    p.wait_for_selector('.sheet[data-sheet="answer"] [data-reply]', timeout=8000)
    text = p.inner_text(".sheet")
    assert "you said" in text.lower() and "bytes of audio" in text
    assert "Speech to text is not part of the fake" in text
    assert sent and sent[0][0].endswith("/api/ask/audio?source=wall")
    assert sent[0][1] in ("audio/webm", "audio/ogg", "audio/mp4", "audio/wav")
    # the microphone is let go
    assert p.evaluate("window.__wall.S.open") == "answer"
    if layout == "a":
        p.wait_for_timeout(500)
        w.shot("19-answer")
    # closes by itself after 8 seconds
    p.wait_for_selector(".sheet", state="detached", timeout=10000)
    assert p.locator("#mic").is_visible()


def test_answer_stays_open_when_touched(make_wall):
    w = make_wall("a").open()
    p = w.page
    hold(p, 900)
    p.mouse.up()
    p.wait_for_selector('.sheet[data-sheet="answer"] [data-reply]', timeout=8000)
    p.click(".sheet [data-reply]")
    assert "Stays open" in p.inner_text(".sheet [data-foot]")
    p.wait_for_timeout(9000)
    assert p.locator('.sheet[data-sheet="answer"]').count() == 1
    w.close()


def test_short_tap_says_hold_to_talk(make_wall):
    w = make_wall("a").open()
    p = w.page
    sent = []
    p.on("request", lambda r: sent.append(r.url) if "/api/ask" in r.url else None)
    hold(p, 120)
    p.mouse.up()
    p.wait_for_selector("#tip:not([hidden])")
    assert p.inner_text("#tip") == "Hold to talk"
    p.wait_for_timeout(1200)
    assert sent == [] and p.locator(".sheet").count() == 0
    assert "listening" not in (p.get_attribute("#mic", "class") or "")


def test_recording_stops_at_15_seconds(make_wall):
    w = make_wall("a").open()
    p = w.page
    hold(p, 15600)                       # still holding
    p.wait_for_selector('.sheet[data-sheet="answer"]', timeout=3000)
    p.mouse.up()
    p.wait_for_selector('.sheet[data-sheet="answer"] [data-reply]', timeout=8000)


def test_mic_denied_still_lets_you_type(make_wall):
    w = make_wall("a", init="""
      Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: () =>
        Promise.reject(new DOMException('Permission denied', 'NotAllowedError')) } });""")
    w.open()
    p = w.page
    hold(p, 600)
    p.mouse.up()
    assert "not allowed" in w.toast()
    assert "keyboard" in p.inner_text("#toast")
    w.shot("20-mic-denied")
    w.sheet("ask")
    p.fill("#askText", "is the aircon on")
    p.keyboard.press("Enter")
    p.wait_for_selector(".sheet [data-reply]")
    assert "I heard: is the aircon on" in p.inner_text(".sheet")


def test_no_microphone_at_all(make_wall):
    w = make_wall("b", init="Object.defineProperty(navigator, 'mediaDevices', { value: undefined });")
    w.open()
    hold(w.page, 600)
    w.page.mouse.up()
    assert "no microphone" in w.toast()


# ---------------------------------------------------------------- typed ask

def test_typed_ask(make_wall):
    w = make_wall("a").open()
    p = w.page
    bodies = []
    p.on("request", lambda r: bodies.append(r.post_data) if r.url.endswith("/api/ask") else None)
    w.sheet("ask")
    w.shot("21-ask")
    p.click('.sheet [data-action="askFill"] >> nth=0')
    assert p.input_value("#askText") == "Make the lounge warmer"
    p.fill("#askText", "make the lounge warmer")
    p.click('.sheet button[type="submit"]')
    p.wait_for_selector('.sheet[data-sheet="answer"] [data-reply]')
    assert "make the lounge warmer" in p.inner_text(".sheet [data-heard]")
    assert p.inner_text(".sheet [data-reply]") == "(fake hub) I heard: make the lounge warmer"
    assert json.loads(bodies[0]) == {"text": "make the lounge warmer", "source": "wall"}
    w.close()


def test_answer_lists_each_action(make_wall):
    w = make_wall("a").open()
    p = w.page
    answer = {"ok": True, "heard": "lounge to 21 and turn on the bedroom tv", "reply": "Done. The lounge is set to 21.",
              "via": "fast", "actions": [
                  {"action": "aircon.set_temp", "args": {"value": 21}, "ok": True},
                  {"action": "tv.power", "args": {"tv": "bedroom", "on": True}, "ok": False, "error": "The TV bridge is not answering."}]}
    p.route(re.compile(r".*/api/ask$"), lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(answer)))
    w.sheet("ask")
    p.fill("#askText", "lounge to 21 and turn on the bedroom tv")
    p.keyboard.press("Enter")
    p.wait_for_selector(".sheet .act.bad")
    acts = p.inner_text(".sheet .acts")
    assert "✓" in acts and "Aircon set to 21°" in acts
    assert "✕" in acts and "Bedroom TV on" in acts and "The TV bridge is not answering." in acts
    p.wait_for_timeout(600)              # let the sheet finish growing into the answer
    w.shot("22-answer-actions")
    w.close()


# ---------------------------------------------------------------- the microphone is only open while held

GUM_SPY = """
  window.__mics = [];
  const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = (c) => real(c).then((s) => { window.__mics.push(s); return s; });
"""


def test_microphone_only_open_while_held(make_wall):
    w = make_wall("a", init=GUM_SPY)
    w.open()
    p = w.page
    # opening the page, tapping cards and sheets never asks for the microphone
    w.sheet("ask")
    w.close()
    w.sheet("music")
    w.close()
    assert p.evaluate("window.__mics.length") == 0
    hold(p, 900)
    assert p.evaluate("window.__mics.length") == 1
    assert p.evaluate("window.__mics[0].getAudioTracks().every(t => t.readyState === 'live')")
    p.mouse.up()
    p.wait_for_selector('.sheet[data-sheet="answer"] [data-reply]', timeout=8000)
    assert p.evaluate("window.__mics.every(s => s.getTracks().every(t => t.readyState === 'ended'))")
    w.close()


# ---------------------------------------------------------------- the hub address, the socket and the window

def test_hub_address_from_the_query_is_ignored(make_wall, hub):
    """Served by a hub, the screen only ever talks to that hub. A link with ?hub=http://other must not
    send the screen's key anywhere else (it used to; ?hub= is now for a copy opened from disk only)."""
    other = "http://hub.test:9999"
    w = make_wall("a")
    p = w.page
    seen = []
    p.route(re.compile(r"^http://hub\.test:9999/.*"), lambda route: (seen.append(route.request.url), route.abort()))
    p.route_web_socket(re.compile(r"^ws://hub\.test:9999/.*"), lambda ws: seen.append(ws.url))
    p.goto(BASE + "/?hub=" + other + f"#key={KEY}")
    w.ready()
    before = len(hub.log())
    p.click('[data-card="aircon"] [data-do="nudge"][data-arg="1"]')
    p.wait_for_function("window.__wall.pending === 0")
    assert seen == [] and len(hub.log()) == before + 1             # it went to this hub, nothing to the other


def test_names_and_place_come_from_the_hub(make_wall):
    """No names or place are written into the wall: they arrive from GET /api/home."""
    w = make_wall("a").open()
    p = w.page
    p.wait_for_selector('[data-action="person"][data-arg="Sam"]')
    names = p.eval_on_selector_all('.who [data-action="person"]', "els => els.map(e => e.dataset.arg)")
    assert names == ["Sam", "Alex"]
    assert "Riverside" in p.inner_text("#ui")
    src = open(__file__.replace("tests/test_wall.py", "app.js")).read()
    assert not re.search(r"\bSam\b|\bAlex\b|Riverside", src)


def test_works_under_its_content_security_policy(make_wall, hub):
    """Every other test bypasses the page's CSP (Playwright's string waits need eval). This one keeps it on:
    the screen still connects, shows art, opens a sheet and runs an action, with no CSP complaint, and
    injected markup cannot run script."""
    w = make_wall("a", context_opts={"bypass_csp": False})
    p = w.page
    csp_errors = []
    p.on("console", lambda m: csp_errors.append(m.text) if "Content Security Policy" in m.text else None)
    p.goto(BASE + f"/#key={KEY}")
    p.wait_for_selector('[data-card="aircon"] [data-set]', timeout=10000)
    p.wait_for_selector('[data-action="person"][data-arg="Sam"]', timeout=10000)
    p.locator('[data-open="aircon"]').first.click()
    p.wait_for_selector(".sheet")
    p.keyboard.press("Escape")
    p.wait_for_selector(".sheet", state="detached")
    before = len(hub.log())
    p.click('[data-card="aircon"] [data-do="nudge"][data-arg="1"]')
    for _ in range(50):
        if len(hub.log()) > before:
            break
        p.wait_for_timeout(100)
    assert len(hub.log()) == before + 1
    assert csp_errors == [], csp_errors
    w.allow("Content Security Policy")
    w.allow("status of 404")                          # the injected <img src=x> itself
    p.evaluate("""() => { const d = document.createElement('div');
        d.innerHTML = '<img src=x onerror="window.__pwned = 1">'; document.body.append(d); }""")
    p.wait_for_timeout(300)
    assert p.evaluate("() => window.__pwned") is None
    csp = p.get_attribute('meta[http-equiv="Content-Security-Policy"]', "content")
    assert "script-src 'self'" in csp and "unsafe" not in csp.split("script-src")[1].split(";")[0]


def test_socket_pings_every_25_seconds(make_wall):
    # the screen's 25 s ping timer runs 100 times faster here
    w = make_wall("a", init="""
      const si = window.setInterval;
      window.setInterval = (fn, ms, ...a) => si(fn, ms === 25000 ? 250 : ms, ...a);""")
    p = w.page
    sent, got = [], []

    def on_ws(ws):
        server = ws.connect_to_server()
        ws.on_message(lambda m: (sent.append(m), server.send(m)))
        server.on_message(lambda m: (got.append(m), ws.send(m)))

    p.route_web_socket(re.compile(r".*/api/events.*"), on_ws)
    w.open()
    p.wait_for_timeout(900)
    pings = [m for m in sent if json.loads(m).get("type") == "ping"]
    pongs = [m for m in got if json.loads(m).get("type") == "pong"]
    assert len(pings) >= 2 and len(pongs) >= 2
    assert p.evaluate("window.__wall.conn") == "online"


def test_scales_to_fit_a_smaller_window(make_wall):
    ctx_wall = make_wall("a")
    p = ctx_wall.page
    p.set_viewport_size({"width": 1000, "height": 700})
    ctx_wall.open()
    box = p.locator("#stage").bounding_box()
    assert abs(box["width"] - 1000) < 1 and abs(box["height"] - 625) < 1
    assert box["x"] >= -0.5 and box["y"] >= -0.5 and box["y"] + box["height"] <= 700.5
    assert box["x"] + box["width"] <= 1000.5
    ctx_wall.shot("23-desktop-window-1000x700")
    # taps still land on the right control when shrunk
    ctx_wall.expect(lambda: p.click('[data-card="aircon"] [data-do="nudge"][data-arg="1"]'), "aircon.nudge", {"delta": 1})
    ctx_wall.sheet("aircon")
    ctx_wall.close()
    p.set_viewport_size({"width": 1280, "height": 800})
    p.wait_for_timeout(100)
    box = p.locator("#stage").bounding_box()
    assert box["width"] == 1280 and box["height"] == 800


def test_only_talks_to_the_hub(make_wall):
    w = make_wall("b")
    p = w.page
    urls = []
    p.on("request", lambda r: urls.append(r.url))
    w.open()
    w.sheet("music")
    w.close()
    p.wait_for_function("Array.from(document.images).every(i => i.complete)")
    art = w.hub.state()["speakers"]["now"]["art"]
    outside = [u for u in urls if not (u.startswith(BASE + "/") or u.startswith("data:") or u == art)]
    assert outside == [], outside


def test_the_clock_is_live(make_wall):
    w = make_wall("a")
    p = w.page
    p.clock.set_fixed_time(datetime(2026, 11, 10, 13, 59, 50))
    w.open()
    assert p.text_content("#clock") == "1:59"
    assert p.text_content("#date") == "Tuesday 10 November"
    p.clock.set_fixed_time(datetime(2026, 11, 11, 0, 0, 5))
    p.wait_for_function("document.getElementById('clock').textContent === '12:00'", timeout=3000)
    assert p.text_content("#date") == "Wednesday 11 November"


# ---------------------------------------------------------------- the Spotify music view

def _linked_music(make_wall, layout="a"):
    w = make_wall(layout)
    w.open()
    w.hub.call("POST", "/fake/spotify", {"linked": True, "idle": True})
    w.page.wait_for_function("document.querySelector('[data-card=\"music\"]') && document.querySelector('[data-card=\"music\"]').innerText.includes('Play music')", timeout=4000)
    return w


@pytest.mark.parametrize("layout", ["a", "b"])
def test_music_card_shows_the_spotify_icon(make_wall, layout):
    w = _linked_music(make_wall, layout)
    icon = w.page.locator('[data-card="music"] img.spicon')
    assert icon.count() == 1 and "spotify-icon-green.svg" in icon.get_attribute("src")
    box = icon.bounding_box()
    assert box["width"] >= 21 and box["height"] >= 21           # Spotify's minimum icon size
    assert w.page.evaluate("document.querySelector('[data-card=\"music\"] img.spicon').naturalWidth") > 0   # the file really loads


def test_music_view_has_logo_tabs_and_tiles(make_wall):
    w = _linked_music(make_wall)
    w.sheet("music")
    w.page.wait_for_selector(".mtile")
    logo = w.page.locator(".sheet img.splogo")
    assert logo.count() == 1 and logo.bounding_box()["width"] >= 70       # Spotify's minimum logo size
    assert w.page.evaluate("document.querySelector('.sheet img.splogo').naturalWidth") > 0
    names = w.page.eval_on_selector_all(".sheet .mtile b", "els => els.map(e => e.innerText)")
    assert names == ["Liked Songs", "Friday Night", "Discover Weekly", "Recently played"]
    assert "AI DJ" not in w.page.inner_text(".sheet")                     # Spotify does not let apps start it
    assert w.page.locator(".sheet .mrow").count() == 2                    # recently played songs
    w.shot("20-music-view-home")
    # every tile is a real tap target
    for box in w.page.locator(".sheet .mtile").all():
        assert box.bounding_box()["height"] >= 80


def test_music_tiles_start_the_right_thing(make_wall):
    w = _linked_music(make_wall)
    w.sheet("music")
    w.page.wait_for_selector(".mtile")
    sel = lambda n: f'.sheet .mtile >> nth={n}'
    w.expect(lambda: w.page.click(sel(0)), "music.start", {"what": "liked", "speakers": ["lounge-room"]})
    w.expect(lambda: w.page.click(sel(1)), "music.start", {"what": "main", "speakers": ["lounge-room"]})
    w.expect(lambda: w.page.click(sel(2)), "music.start", {"what": "discover", "speakers": ["lounge-room"]})
    w.expect(lambda: w.page.click(sel(3)), "music.start", {"what": "recent", "speakers": ["lounge-room"]})
    w.expect(lambda: w.page.click(".sheet .mrow >> nth=0"), "music.start",
             {"what": "uri", "uri": "spotify:track:aaaaaaaaaaaa", "speakers": ["lounge-room"]})


def test_music_play_on_chips_choose_the_speakers(make_wall):
    w = _linked_music(make_wall)
    w.sheet("music")
    w.page.wait_for_selector(".mtile")
    w.page.click('.sheet [data-mplayon] [data-arg="theatre"]')
    w.expect(lambda: w.page.click(".sheet .mtile >> nth=0"), "music.start", {"what": "liked", "speakers": ["lounge-room", "theatre"]})


def test_music_search_plays_what_is_tapped(make_wall):
    w = _linked_music(make_wall)
    w.sheet("music")
    w.page.click('.sheet [data-do="mTab"][data-arg="search"]')
    assert w.page.locator("#msearch").is_visible()
    w.page.fill("#msearch", "daft punk")
    w.page.dispatch_event("#msearch", "input")
    w.page.wait_for_selector(".sheet .mrow", timeout=4000)
    text = w.page.inner_text(".sheet")
    for want in ("Songs", "Artists", "Albums", "Playlists", "Daft Punk", "Discovery", "This Is Daft Punk"):
        assert want.lower() in text.lower()
    w.shot("21-music-view-search")
    # a state update (the hub pushes them all the time) must not wipe the search box
    w.hub.call("POST", "/api/action", {"action": "aircon.set_temp", "args": {"value": 21}}, key=KEY)
    w.page.wait_for_timeout(500)
    assert w.page.input_value("#msearch") == "daft punk"
    w.expect(lambda: w.page.click('.sheet .mrow[data-arg="spotify:album:eeeeeeeeeeee"]'), "music.start",
             {"what": "uri", "uri": "spotify:album:eeeeeeeeeeee", "speakers": ["lounge-room"]})
    # nothing found says so, plainly
    w.page.fill("#msearch", "nothing")
    w.page.dispatch_event("#msearch", "input")
    w.page.wait_for_function("document.querySelector('.sheet').innerText.includes('found nothing')", timeout=4000)
    # clear
    w.page.click('.sheet [data-do="mClear"]')
    assert w.page.input_value("#msearch") == ""


def test_music_playlists_and_changing_the_main_one(make_wall):
    w = _linked_music(make_wall)
    w.sheet("music")
    w.page.click('.sheet [data-do="mTab"][data-arg="playlists"]')
    w.page.wait_for_selector(".sheet .mcard")
    assert w.page.locator(".sheet .mcard").count() == 4
    assert "Main" in w.page.inner_text(".sheet .mcard.isMain")
    w.shot("22-music-view-playlists")
    w.expect(lambda: w.page.click('.sheet .mcard[data-arg="playlist:FakePlaylist0000000002"]'), "music.start",
             {"what": "playlist", "playlist": "FakePlaylist0000000002", "speakers": ["lounge-room"]})
    # change the main playlist: the next tap picks it instead of playing it
    w.page.click('.sheet [data-do="mPickMain"]')
    assert "Tap the playlist you want as your main one" in w.page.inner_text(".sheet")
    before = len(w.hub.log())
    w.page.click('.sheet .mcard[data-arg="FakePlaylist0000000004"]')
    w.page.wait_for_function("document.querySelector('.sheet .mcard.isMain') && document.querySelector('.sheet .mcard.isMain').innerText.includes('Cocktail hour')", timeout=4000)
    log = w.hub.log()[before:]
    assert log[0]["action"] == "main" and log[0]["args"] == {"playlist": "FakePlaylist0000000004"}
    assert not any(e["action"] == "music.start" for e in log)


def test_music_now_playing_shuffle_and_speaker_tab(make_wall):
    w = _linked_music(make_wall)
    w.sheet("music")
    w.page.wait_for_selector(".mtile")
    w.expect(lambda: w.page.click(".sheet .mtile >> nth=0"), "music.start")
    w.page.wait_for_selector('.sheet [data-do="shuffle"]')
    before = len(w.hub.log())
    w.page.click('.sheet [data-do="shuffle"]')
    w.page.wait_for_function("document.querySelector('.sheet [data-do=\"shuffle\"]').classList.contains('green')", timeout=4000)
    assert w.hub.log()[before]["action"] == "shuffle" and w.hub.log()[before]["args"] == {"on": True}
    # the speaker tab keeps the per speaker rows and volume
    w.page.click('.sheet [data-do="mTab"][data-arg="speakers"]')
    assert w.page.locator('.sheet .spk[data-spk="theatre"]').count() == 1
    w.shot("23-music-view-playing")


def test_music_not_linked_still_has_the_logo_and_controls(make_wall):
    w = make_wall("a").open()
    w.sheet("music")
    assert w.page.locator(".sheet img.splogo").count() == 1
    assert "Spotify is not linked yet" in w.page.inner_text(".sheet")
    assert w.page.locator('.sheet [data-do="playPause"]').count() == 1
    assert w.page.locator('.sheet [data-do="shuffle"]').count() == 0
