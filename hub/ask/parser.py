"""The fast path: a plain rule parser for common house commands. No AI, a few milliseconds.

parse(text, state) -> Plan | None

A Plan is a list of contract actions plus a short reply to show when they all work. None means
"not sure": the engine then asks Claude. Every rule must match the WHOLE sentence (after polite
words are dropped), so anything unusual ("make it cosy for a movie", "don't turn on the TV") falls
through to Claude instead of being half understood.

The lounge trap: "lounge" / "living room" can mean the Living aircon zone, the Lounge Room speaker
or the Living Room TV. Those words only count when the sentence also says which kind of thing it is
(aircon/vent/warmer words, music/speaker words, or TV/app words). Otherwise: Claude.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- plans


@dataclass
class Plan:
    actions: list = field(default_factory=list)   # [(action, args)]
    reply: str = ""
    tv: str | None = None                         # the TV this clause was about (for "and open Netflix")
    tv_on: set = field(default_factory=set)       # TVs this plan turns on

    def __add__(self, other):
        return Plan(self.actions + other.actions, f"{self.reply} {other.reply}".strip(),
                    other.tv or self.tv, self.tv_on | other.tv_on)


class Ambiguous(Exception):
    """A rule saw the sentence and knows it cannot be sure. Stop and ask Claude."""


# ---------------------------------------------------------------- state helpers

ZONE_IDS = ["living", "media", "rumpus", "master-bed", "bed-2", "bed-3", "bed-4"]
ZONE_NAMES = {"living": "Living", "media": "Media", "rumpus": "Rumpus", "master-bed": "Master Bed",
              "bed-2": "Bed 2", "bed-3": "Bed 3", "bed-4": "Bed 4"}
SPEAKER_NAMES = {"lounge-room": "Lounge Room", "theatre": "Theatre", "outside": "Outside"}
TV_NAMES = {"living-room": "Living Room", "bedroom": "Bedroom", "frame": "The Frame"}
DEFAULT_APPS = ["YouTube", "Netflix", "Stan", "ABC iview", "SBS On Demand", "Disney+", "Prime Video", "Live TV"]
FAN_ORDER = ["auto", "quiet", "low", "medium", "high", "powerful", "turbo"]


class Ctx:
    def __init__(self, state, last_tv=None, tv_on=frozenset()):
        self.state = state or {}
        self.last_tv = last_tv
        self.tv_on_planned = set(tv_on)

    def after(self, plan):
        return Ctx(self.state, plan.tv or self.last_tv, self.tv_on_planned | plan.tv_on)

    # aircon
    @property
    def ac(self):
        return self.state.get("aircon") or {}

    def set_temp(self):
        v = self.ac.get("set")
        return v if isinstance(v, (int, float)) else None

    def ac_power(self):
        return self.ac.get("power")

    def zone_on(self, zid):
        for z in self.ac.get("zones") or []:
            if z.get("id") == zid:
                return z.get("on")
        return None

    def zone_name(self, zid):
        for z in self.ac.get("zones") or []:
            if z.get("id") == zid and z.get("name"):
                return z["name"]
        return ZONE_NAMES[zid]

    def fan_speeds(self):
        return [f for f in (self.ac.get("fan_speeds") or FAN_ORDER) if f in FAN_ORDER] or FAN_ORDER

    def fan(self):
        return self.ac.get("fan")

    # speakers
    @property
    def sp(self):
        return self.state.get("speakers") or {}

    def now(self):
        return self.sp.get("now")

    def music_playing(self):
        n = self.now()
        return bool(n and n.get("playing"))

    def speakers_in_use(self):
        n = self.now()
        if n and n.get("on"):
            return list(n["on"])
        return [d["id"] for d in self.sp.get("devices") or [] if d.get("in_use")]

    def speaker_volume(self, sid):
        for d in self.sp.get("devices") or []:
            if d.get("id") == sid:
                return d.get("volume")
        return None

    # tvs
    @property
    def tvs(self):
        return self.state.get("tvs") or {}

    def tv(self, tid):
        for t in self.tvs.get("devices") or []:
            if t.get("id") == tid:
                return t
        return {}

    def tv_is_on(self, tid):
        return tid in self.tv_on_planned or self.tv(tid).get("power") == "on"

    def tvs_on(self):
        on = [t["id"] for t in self.tvs.get("devices") or [] if t.get("power") == "on"]
        return on + [t for t in self.tv_on_planned if t not in on]

    def tv_label(self, tid):
        name = self.tv(tid).get("name") or TV_NAMES[tid]
        return name if tid == "frame" else f"{name} TV"

    def apps(self):
        return self.tvs.get("apps") or DEFAULT_APPS

    def pick_tv(self):
        """The TV a sentence without a TV name means: the one just named, or the only one that is on."""
        if self.last_tv:
            return self.last_tv
        on = self.tvs_on()
        if len(on) == 1:
            return on[0]
        raise Ambiguous("which TV")


# ---------------------------------------------------------------- normalising

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}


def _numbers(words):
    out, i = [], 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if w in _TENS:
            if nxt in _ONES and 0 < _ONES[nxt] < 10:
                out.append(str(_TENS[w] + _ONES[nxt]))
                i += 2
                continue
            out.append(str(_TENS[w]))
        elif w in ("hundred", "100") and out and out[-1] in ("a", "1", "one"):
            out[-1] = "100"
        elif w == "one" and nxt == "hundred":
            out.append("1")
        elif w in _ONES and w != "one":
            out.append(str(_ONES[w]))
        else:
            out.append(w)
        i += 1
    return out


_LEAD = re.compile(r"^(?:(?:hey|hi|ok|okay|so|right|alright|now|um|uh|er|please|hub|house|home|"
                   r"can you|could you|would you|will you|can we|could we|i want to|i want you to|"
                   r"id like to|id like you to|i would like to|i need you to|lets|let us|go ahead and|"
                   r"quickly|kindly)\s+)+")
_TAIL = re.compile(r"(?:\s+(?:and |so )?(?:please|thanks|thank you|for me|for us|now|right now|ok|okay|mate|cheers|"
                   r"if you can|if you could|when you can|thanks mate|hub))+$")

_SUBS = [
    (r"\bair[ -]?con(?:ditioner|ditioning|ditioners)?s?\b", "aircon"),
    (r"\ba ?/ ?c\b|\ba\.c\.?|\bac\b|\bhvac\b", "aircon"),
    (r"\b(?:television|telly|t\.v\.?|tele)\b", "tv"),
    (r"\btelevisions\b|\btv'?s\b", "tvs"),
    (r"\btheater\b", "theatre"),
    (r"(\d)\s*(?:°|º)\s*c?\b", r"\1 degrees"),
    (r"°|º", " degrees"),
    (r"\bdegrees? (?:celsius|c)\b", "degrees"),
    (r"\bdegree\b", "degrees"),
    (r"(\d)\s*(?:%|percent|per cent)", r"\1"),
    (r"\bmaster'?s\b", "master"),
    (r"\bspotify'?s\b", "spotify"),
    (r"\bwi-?fi\b", "wifi"),
    (r"\bdisney ?(?:\+|plus)", "disney+"),
]


def normalize(text: str) -> str:
    t = (text or "").lower().replace("’", "'").replace("‘", "'")
    for pat, rep in _SUBS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", t)           # twenty-two, wi-fi
    t = re.sub(r"'", "", t)                                # it's -> its, don't -> dont
    t = re.sub(r"[^\w\s+]", " ", t)                        # punctuation (keep + for disney+)
    t = re.sub(r"(?<!\w)\+|\+(?!\s|$)", " ", t)
    words = _numbers(t.split())
    t = " ".join(w for w in words if w not in ("the", "um", "uh", "er", "erm"))
    t = re.sub(r"\ba couple (?:of )?degrees\b", "2 degrees", t)
    t = re.sub(r"\ba degrees\b", "1 degrees", t)
    t = re.sub(r"\ball of\b", "all", t)
    t = re.sub(r"\b(\d+) degrees\b", r"\1 degrees", t)
    t = re.sub(r"\btv in (living room|lounge room|lounge|bedroom|family room)\b", r"\1 tv", t)
    t = re.sub(r"\b(?:a )?(?:little|tad|touch|wee) bit\b|\ba (?:little|tad|touch)\b|\ba bit\b|\blittle\b", "bit", t)
    t = re.sub(r"\b(?:a )?(?:lot|heaps|way|much|whole lot)\b", "lot", t)
    # "turn it down a bit" -> "turn it bit down", so the amount always sits before the direction
    t = re.sub(r"\b(up|down|louder|quieter|softer|warmer|cooler|hotter|colder|lower|higher) (bit|lot)\b", r"\2 \1", t)
    for _ in range(3):
        t = _LEAD.sub("", t).strip()
        t = _TAIL.sub("", t).strip()
    return re.sub(r"\s+", " ", t).strip()


# Sentences with these words are never guessed at: questions, "don't", timers, conditions.
_GUARD = {"not", "dont", "never", "without", "except", "unless", "but", "nothing", "no", "isnt", "wont",
          "cant", "doesnt", "shouldnt", "wouldnt", "minutes", "minute", "hour", "hours", "tonight",
          "tomorrow", "later", "until", "till", "timer", "oclock", "pm", "after", "before", "when",
          "if", "while", "daily", "everyday", "schedule", "remind", "ignore", "pretend", "instead", "why", "maybe"}
_QUESTION_START = {"what", "whats", "why", "how", "hows", "when", "where", "which", "who", "whos", "is",
                   "are", "does", "do", "did", "can", "could", "should", "would", "will", "tell", "whose",
                   "am", "was", "were", "has", "have"}
# Words that mean a free-text title or query is really a wish for Claude, not a name.
_VAGUE = {"something", "anything", "whatever", "stuff", "good", "nice", "random", "recommend",
          "different", "else", "favourite", "favorite", "usual", "my", "our", "last", "latest", "new",
          "same", "movie", "film", "show", "episode", "series", "music", "song", "songs", "tunes",
          "it", "this", "that", "them", "kids", "relaxing", "chill", "cosy", "cozy", "romantic",
          "scary", "funny", "tv", "aircon", "speaker", "speakers", "volume", "louder", "quieter",
          "vent", "vents", "zone", "temperature", "temp", "degrees", "warmer", "cooler", "season",
          "next", "previous", "again"}


# ---------------------------------------------------------------- vocabulary

def _alt(words):
    return "(?:" + "|".join(sorted(words, key=len, reverse=True)) + ")"


# aircon zones: unique words always mean a zone; shared words only with an aircon word
ZONE_UNIQUE = {
    "media": ["media room", "media"],
    "rumpus": ["rumpus room", "rumpus", "games room"],
    "master-bed": ["master bedroom", "master bed room", "master bed", "master", "main bedroom", "our bedroom",
                   "our room", "parents room", "parents bedroom"],
    "bed-2": ["bed 2", "bedroom 2", "bed room 2", "second bedroom", "2nd bedroom", "room 2"],
    "bed-3": ["bed 3", "bedroom 3", "bed room 3", "third bedroom", "3rd bedroom", "room 3"],
    "bed-4": ["bed 4", "bedroom 4", "bed room 4", "fourth bedroom", "4th bedroom", "room 4"],
}
ZONE_SHARED = {"living": ["living room", "living area", "living", "lounge room", "lounge", "family room"]}
_ZSUFFIX = r"(?: room)?(?: zone| vent| vents| aircon)?"


def _zone_one(shared):
    words = [w for ws in ZONE_UNIQUE.values() for w in ws]
    if shared:
        words += [w for ws in ZONE_SHARED.values() for w in ws]
    return _alt(words) + _ZSUFFIX


def _zone_list(shared):
    one = _zone_one(shared)
    return rf"{one}(?:(?:,| and| plus| &|, and) {one})*"


ZL_U, ZL_A = _zone_list(False), _zone_list(True)


def zones_in(text):
    found = []
    allz = {**ZONE_UNIQUE, **ZONE_SHARED}
    words = sorted(((w, z) for z, ws in allz.items() for w in ws), key=lambda x: -len(x[0]))
    rest = text
    hits = []
    for w, z in words:
        for m in re.finditer(rf"\b{re.escape(w)}\b", rest):
            hits.append((m.start(), z))
        rest = re.sub(rf"\b{re.escape(w)}\b", lambda m: "#" * len(m.group(0)), rest)
    for _, z in sorted(hits):
        if z not in found:
            found.append(z)
    return found


SPK_UNIQUE = {"theatre": ["home theatre", "theatre room", "theatre"],
              "outside": ["outside", "outdoors", "outdoor", "back deck", "deck", "patio", "backyard", "back yard"]}
SPK_SHARED = {"lounge-room": ["lounge room", "lounge", "living room"]}
_SSUFFIX = r"(?: speakers?)?"


def _spk_one(shared):
    words = [w for ws in SPK_UNIQUE.values() for w in ws]
    if shared:
        words += [w for ws in SPK_SHARED.values() for w in ws]
    return _alt(words) + _SSUFFIX


def _spk_list(shared):
    one = _spk_one(shared)
    return rf"{one}(?:(?:,| and| plus| &|, and) {one})*"


SL_U, SL_A = _spk_list(False), _spk_list(True)


def speakers_in(text):
    allspk = {**SPK_UNIQUE, **SPK_SHARED}
    words = sorted(((w, s) for s, ws in allspk.items() for w in ws), key=lambda x: -len(x[0]))
    rest, hits = text, []
    for w, s in words:
        for m in re.finditer(rf"\b{re.escape(w)}\b", rest):
            hits.append((m.start(), s))
        rest = re.sub(rf"\b{re.escape(w)}\b", lambda m: "#" * len(m.group(0)), rest)
    out = []
    for _, s in sorted(hits):
        if s not in out:
            out.append(s)
    return out


EVERYWHERE = r"(?:everywhere|in every room|every room|all rooms|whole house|all speakers|all 3 speakers|every speaker|all 3|all of them|both inside and outside)"

TV_REF = {
    "living-room": ["living room tv", "lounge room tv", "lounge tv", "main tv", "big tv", "family room tv",
                    "google tv"],
    "bedroom": ["bedroom tv"],
    "frame": ["samsung frame tv", "samsung frame", "frame tv", "samsung tv", "samsung", "frame", "art tv"],
}
# Where a TV can be named by its room alone (only once the sentence is clearly about a TV).
TV_ROOM = {"living-room": ["living room", "lounge room", "lounge", "family room"], "bedroom": ["bedroom"],
           "frame": []}
TVR = _alt([w for ws in TV_REF.values() for w in ws])
TVR_G = _alt([w for ws in TV_REF.values() for w in ws] + ["tv"])
TVLOC = _alt([w for ws in TV_REF.values() for w in ws] + [w for ws in TV_ROOM.values() for w in ws])


def add_tv_words(extra):
    """More names for the TVs, such as a brand ("the sony"), from config.json "ask": {"tv_words":
    {"bedroom": ["sony tv", "sony"]}}. Kept in config so this file names no one's own TVs."""
    global TVR, TVR_G, TVLOC
    for tid, words in (extra or {}).items():
        if tid not in TV_REF or not isinstance(words, list):
            continue
        for w in words:
            w = " ".join(str(w).lower().split())
            if re.fullmatch(r"[a-z0-9][a-z0-9 +'-]{1,29}", w) and w not in TV_REF[tid]:
                TV_REF[tid].append(w)
    TVR = _alt([w for ws in TV_REF.values() for w in ws])
    TVR_G = _alt([w for ws in TV_REF.values() for w in ws] + ["tv"])
    TVLOC = _alt([w for ws in TV_REF.values() for w in ws] + [w for ws in TV_ROOM.values() for w in ws])


def tv_of(word, ctx):
    word = re.sub(r"\s+", " ", word.strip())
    for tid, ws in TV_REF.items():
        if word in ws:
            return tid
    for tid, ws in TV_ROOM.items():
        if word in ws:
            return tid
    if word in ("tv", ""):
        return None
    raise Ambiguous(word)


APP_ALIASES = {
    "youtube": "YouTube", "you tube": "YouTube", "netflix": "Netflix", "stan": "Stan",
    "abc iview": "ABC iview", "iview": "ABC iview", "abc": "ABC iview", "i view": "ABC iview",
    "sbs on demand": "SBS On Demand", "sbs": "SBS On Demand", "disney+": "Disney+", "disney": "Disney+",
    "prime video": "Prime Video", "amazon prime": "Prime Video", "prime": "Prime Video",
    "amazon": "Prime Video", "live tv": "Live TV", "free to air": "Live TV", "free to air tv": "Live TV",
}


def _app_words(ctx):
    words = dict(APP_ALIASES)
    for a in ctx.apps():
        words.setdefault(re.sub(r"[^\w\s+]", " ", a.lower()).strip(), a)
    return words


def _app_re(ctx):
    return _alt([re.escape(w) for w in _app_words(ctx)])


# ---------------------------------------------------------------- helpers

def _m(pattern, t):
    return re.fullmatch(pattern, t)


def _and(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _amount(word, small, normal, big):
    if not word:
        return normal
    return big if "lot" in word else small if "bit" in word else normal


def _clean_free(text):
    """A free-text title/query, or None when it is really a vague wish."""
    q = re.sub(r"^(?:some|a few|few)\s+", "", text.strip())
    q = re.sub(r"^(?:songs?|music|tracks?|stuff) by\s+", "", q)
    q = re.sub(r"\s+on spotify$", "", q)
    words = q.split()
    if not words or len(q) > 100 or any(w in _VAGUE for w in words):
        return None
    return q


_SMALL = {"of", "the", "and", "a", "an", "in", "on", "by", "to", "for", "at"}


def _title_case(q, original):
    """Find the words in the person's own text (keeps their capitals and any 'the'); else title-case."""
    words = q.split()
    orig = re.sub(r"[^\w\s'+&:-]", " ", original or "")
    pat = r"(?i)\b((?:the\s+)?" + r"[\s,]+(?:the\s+)?".join(re.escape(w) for w in words) + r")\b"
    m = re.search(pat, orig)
    if m:
        found = re.sub(r"\s+", " ", m.group(1)).strip()
        if found != found.lower():
            return found
        q = found.lower()
    out = []
    for i, w in enumerate(q.split()):
        out.append(w if (i and w in _SMALL) else (w[:1].upper() + w[1:]))
    return " ".join(out)


def _music_hint(t):
    return bool(re.search(r"\b(?:music|songs?|playlist|album|radio|spotify|tunes|by|artist|band|track)\b", t))


# ---------------------------------------------------------------- rules
# Each rule takes (t, ctx, original) and returns a Plan, None (not mine) or raises Ambiguous.

RULES = []


def rule(fn):
    RULES.append(fn)
    return fn


# ----- TVs first: they have the clearest words (tv, app names, frame, art mode)

@rule
def art_mode(t, ctx, o):
    if "art" not in t:
        return None
    on = None
    if _m(r"(?:(?:turn|switch|put) )?(?:(?P<a>on|off) )?(?:frame |frame tv )?(?:in |into |to |on )?art mode(?: (?P<b>on|off))?(?: (?:on|for) (?:frame|frame tv))?", t) \
            or _m(r"(?:put|switch|turn|set) (?:frame|frame tv) (?:in|into|to|on) art mode", t):
        m = _m(r"(?:(?:turn|switch|put) )?(?:(?P<a>on|off) )?(?:frame |frame tv )?(?:in |into |to |on )?art mode(?: (?P<b>on|off))?(?: (?:on|for) (?:frame|frame tv))?", t)
        on = not (m and "off" in (m.group("a"), m.group("b")))
    elif _m(r"(?:show|display) (?:some )?art(?: on (?:frame|frame tv))?", t):
        on = True
    elif _m(r"(?:exit|leave|stop|end|turn off) art mode(?: on (?:frame|frame tv))?", t):
        on = False
    if on is None:
        return None
    return Plan([("tv.art_mode", {"tv": "frame", "on": on})], f"Art mode {'on' if on else 'off'}.", tv="frame")


def _with_power(ctx, tv):
    """Turn the TV on first if it is off (an app or a show needs it on)."""
    if ctx.tv_is_on(tv):
        return [], set()
    return [("tv.power", {"tv": tv, "on": True})], {tv}


@rule
def tv_launch(t, ctx, o):
    app_re = _app_re(ctx)
    m = (_m(rf"(?:open|launch|start|load|go to|switch to|change to|put on|put|bring up|run|turn on) (?P<app>{app_re})(?: app)?(?: (?:on|in) (?P<loc>{TVLOC}))?", t)
         or _m(rf"(?:open|launch|start|put|put on) (?P<app>{app_re})(?: app)? on(?: (?:on|in) (?P<loc>{TVLOC}))?", t)
         or _m(rf"(?:put|switch|change|turn) (?P<loc>{TVLOC}) (?:to|on|onto|over to) (?P<app>{app_re})", t)
         or _m(rf"(?:open|launch|start) (?P<loc>{TVLOC}) (?P<app>{app_re})", t)
         or _m(rf"(?P<app>{app_re})(?: app)? (?:on|in) (?P<loc>{TVLOC})", t)
         or _m(rf"(?P<app>{app_re})(?: app)? on", t))
    if not m:
        return None
    app = _app_words(ctx)[m.group("app")]
    loc = m.groupdict().get("loc")
    tv = tv_of(loc, ctx) if loc else None
    tv = tv or ctx.pick_tv()
    pre, on = _with_power(ctx, tv)
    return Plan(pre + [("tv.launch", {"tv": tv, "app": app})],
                f"Opening {app} on the {ctx.tv_label(tv)}.", tv=tv, tv_on=on)


@rule
def tv_power(t, ctx, o):
    m = (_m(rf"(?:turn|switch|power) (?P<on>on|off) (?P<tv>{TVR_G})", t)
         or _m(rf"(?:turn|switch|power) (?P<tv>{TVR_G}) (?P<on>on|off)", t)
         or _m(rf"(?P<tv>{TVR_G}) (?P<on>on|off)", t)
         )
    if m:
        on = m.group("on") == "on"
        word = m.group("tv")
        tv = tv_of(word, ctx)
        if tv is None:                          # just "the TV"
            on_now = ctx.tvs_on()
            if not on and len(on_now) == 1:
                tv = on_now[0]
            elif not on and not on_now:
                return Plan([], "The TVs are already off.")
            else:
                raise Ambiguous("which tv")
        return Plan([("tv.power", {"tv": tv, "on": on})], f"{ctx.tv_label(tv)} {'on' if on else 'off'}.",
                    tv=tv, tv_on={tv} if on else set())
    m = (_m(r"(?:turn|switch) (?P<on>on|off) (?:all|both|all 3) tvs?", t)
         or _m(r"(?:turn|switch) (?:all|both|all 3) tvs? (?P<on>on|off)", t)
         or _m(r"(?:all|both) tvs? (?P<on>on|off)", t)
         or _m(r"(?:turn|switch) (?P<on>off) tvs", t))
    if m:
        on = m.group("on") == "on"
        ids = list(TV_NAMES) if on else (ctx.tvs_on() or list(TV_NAMES))
        return Plan([("tv.power", {"tv": i, "on": on}) for i in ids], f"TVs {'on' if on else 'off'}.",
                    tv_on=set(ids) if on else set())
    return None


@rule
def tv_volume(t, ctx, o):
    amt = r"(?:(?P<amt>bit|lot) )?"
    m = (_m(rf"(?:turn |make )?(?P<tv>{TVR_G})(?: volume| sound)? {amt}(?P<d>up|down|louder|quieter|softer|lower)(?: (?:by )?(?P<n>\d+))?", t)
         or _m(rf"turn (?P<d>up|down) (?P<tv>{TVR_G})(?: volume| sound)?(?: (?:by )?(?P<n>\d+))?", t)
         or _m(rf"turn (?P<tv>{TVR_G})(?: volume| sound)? {amt}(?P<d>up|down)(?: (?:by )?(?P<n>\d+))?", t)
         or _m(rf"(?:turn )?(?:tv )?volume (?P<d>up|down)(?: (?:by )?(?P<n>\d+))? (?:on|for) (?P<tv>{TVR_G})", t)
         or _m(rf"(?:turn )?(?P<d>up|down) volume (?:on|for) (?P<tv>{TVR_G})", t))
    if m:
        up = m.group("d") in ("up", "louder")
        n = m.groupdict().get("n")
        step = int(n) if n else _amount(m.groupdict().get("amt"), 2, 3, 6)
        if not 1 <= step <= 10:
            raise Ambiguous("tv volume step")
        tv = tv_of(m.group("tv"), ctx) or ctx.pick_tv()
        return Plan([("tv.volume", {"tv": tv, "delta": step if up else -step})],
                    f"{ctx.tv_label(tv)} {'louder' if up else 'quieter'}.", tv=tv)
    m = _m(rf"(?:set )?(?P<tv>{TVR_G}) volume (?:to|at) (?P<n>\d+)", t) or \
        _m(rf"(?:set )?volume (?:on|of|for) (?P<tv>{TVR_G}) (?:to|at) (?P<n>\d+)", t)
    if m:
        tv = tv_of(m.group("tv"), ctx) or ctx.pick_tv()
        cur = ctx.tv(tv).get("volume")
        if not isinstance(cur, int):
            raise Ambiguous("tv volume unknown")
        delta = max(-10, min(10, int(m.group("n")) - cur))
        if delta == 0:
            return Plan([], f"The {ctx.tv_label(tv)} is already at {cur}.", tv=tv)
        return Plan([("tv.volume", {"tv": tv, "delta": delta})], f"{ctx.tv_label(tv)} volume to {cur + delta}.", tv=tv)
    return None


@rule
def tv_mute(t, ctx, o):
    m = (_m(rf"(?P<v>mute|unmute)(?: (?P<tv>{TVR_G}))?", t)
         or _m(rf"(?P<tv>{TVR_G}) (?P<v>mute|unmute|muted|on mute|off mute)", t)
         or _m(rf"(?:put|turn) (?P<tv>{TVR_G}) (?P<v>on mute|off mute)", t)
         or _m(rf"(?:take) (?P<tv>{TVR_G}) (?P<v>off mute)", t)
         or _m(rf"(?:turn )?(?P<v>sound) (?:back )?on (?:on )?(?P<tv>{TVR_G})", t))
    if not m:
        return None
    muted = m.group("v") in ("mute", "muted", "on mute")
    word = m.groupdict().get("tv")
    if word:
        tv = tv_of(word, ctx) or ctx.pick_tv()
    else:                                   # just "mute": only when a single TV is the obvious one
        if ctx.music_playing():
            raise Ambiguous("mute what")
        tv = ctx.pick_tv()
    return Plan([("tv.mute", {"tv": tv, "muted": muted})], f"{ctx.tv_label(tv)} {'muted' if muted else 'unmuted'}.", tv=tv)


_TV_ROOM_SHARED = {"living room", "lounge room", "lounge", "family room"}


@rule
def tv_play(t, ctx, o):
    app_re = _app_re(ctx)
    verbs = r"(?P<verb>put on|play|watch|start|stream|show|find and play|find)"
    m = (_m(rf"{verbs} (?P<title>.+?)(?: on (?P<app>{app_re}))? (?:in|on) (?P<loc>{TVLOC})(?: on (?P<app2>{app_re}))?", t)
         or _m(rf"(?P<verb>put) (?P<title>.+?) on (?:(?:in|on) )?(?P<loc>{TVLOC})", t)
         or _m(rf"{verbs} (?P<title>.+?) on (?P<app>{app_re})", t)
         or _m(rf"(?P<verb>watch) (?P<title>.+?)", t))
    if not m:
        return None
    loc = m.groupdict().get("loc")
    has_app = bool(m.groupdict().get("app") or m.groupdict().get("app2"))
    verb = m.group("verb")
    title = _clean_free(m.group("title"))
    if not title:
        if verb == "watch" or has_app or (loc and loc not in _TV_ROOM_SHARED):
            raise Ambiguous("vague title")      # "put on something good in the bedroom": Claude
        return None                             # "play music in the lounge": the music rules
    if loc in _TV_ROOM_SHARED and verb != "watch" and not has_app:
        raise Ambiguous("lounge: tv or speaker")   # "play X in the lounge": music or a show?
    if title in _app_words(ctx):
        return None                                # "put on Netflix" is an app, see tv_launch
    if loc:
        tv = tv_of(loc, ctx)
    else:
        tv = ctx.pick_tv()
    pre, on = _with_power(ctx, tv)
    nice = _title_case(title, o)
    return Plan(pre + [("tv.play", {"tv": tv, "title": nice})], f"Putting {nice} on the {ctx.tv_label(tv)}.",
                tv=tv, tv_on=on)


# ----- aircon

_AC = r"(?:aircon|heating|heater|cooling|air)"


@rule
def aircon_power(t, ctx, o):
    m = (_m(r"(?:turn|switch|put|power) (?P<on>on|off) (?P<w>aircon|heating|heater|cooling)", t)
         or _m(r"(?:turn|switch|put|power) (?P<w>aircon|heating|heater|cooling) (?P<on>on|off)", t)
         or _m(r"(?P<w>aircon|heating|heater|cooling) (?P<on>on|off)", t)
         or _m(r"(?P<on>start|stop|kill|shut down|shut off) (?P<w>aircon|heating|heater|cooling)", t)
         or _m(r"(?:turn|switch|shut) (?P<w>aircon) (?P<on>off)", t))
    if not m:
        if _m(r"(?:turn|bump|put) (?:aircon (?:bit |lot )?(?:up|down)|(?:up|down) aircon)", t):
            raise Ambiguous("aircon up: warmer or more cooling?")
        return None
    on = m.group("on") in ("on", "start")
    w = m.group("w")
    if on and w in ("heating", "heater"):
        return Plan([("aircon.mode", {"mode": "heat"})], "Heating on.")
    if on and w == "cooling":
        return Plan([("aircon.mode", {"mode": "cool"})], "Cooling on.")
    return Plan([("aircon.power", {"on": on})], f"Aircon {'on' if on else 'off'}.")


def _temp_plan(ctx, n, anchored, zone=None, power=False):
    if not 16 <= n <= 30:
        if anchored:
            return Plan([], "I can set the aircon from 16 to 30 degrees.")
        raise Ambiguous("number out of range")
    acts = []
    if power and ctx.ac_power() is not True:
        acts.append(("aircon.power", {"on": True}))
    acts.append(("aircon.set_temp", {"value": n}))
    reply = f"Set to {n}°."
    if zone and ctx.zone_on(zone) is not True:
        acts.append(("aircon.zone", {"zone": zone, "on": True}))
        reply = f"Set to {n}° with {ctx.zone_name(zone)} on."
    if not power and ctx.ac_power() is False:
        reply += " The aircon is off."
    return Plan(acts, reply)


@rule
def aircon_temp(t, ctx, o):
    deg = r"(?: degrees)?"
    m = _m(rf"(?:turn |switch )?aircon on (?:to |at |and set (?:it )?to )?(?P<n>\d+){deg}", t) or \
        _m(rf"(?:turn|switch) on aircon (?:to|at) (?P<n>\d+){deg}", t)
    if m:
        return _temp_plan(ctx, int(m.group("n")), True, power=True)
    m = (_m(rf"(?:set|put|change|turn|make|bring|keep) (?:aircon |temp |temperature |thermostat |aircon temp |aircon temperature |house |it )?(?:to |at |on )?(?P<n>\d+)(?P<deg> degrees)?", t)
         or _m(rf"(?P<a>aircon|temp|temperature|thermostat)(?: temp| temperature)? (?:to|at|on) (?P<n>\d+)(?P<deg> degrees)?", t)
         or _m(rf"(?P<n>\d+)(?P<deg> degrees)", t))
    if m:
        anchored = bool(m.groupdict().get("deg") or m.groupdict().get("a") or
                        re.search(r"\b(?:aircon|temp|temperature|thermostat)\b", t))
        if not anchored and not re.fullmatch(r"(?:set|make|put|turn|change) it (?:to |at )?\d+", t):
            raise Ambiguous("bare number")
        return _temp_plan(ctx, int(m.group("n")), anchored)
    m = _m(rf"(?:set|put|make|keep) (?P<z>{ZL_A}) (?:to|at) (?P<n>\d+) degrees", t) or \
        _m(rf"(?:set )?(?P<z>{ZL_A}) (?:to|at) (?P<n>\d+) degrees", t)
    if m:
        zs = zones_in(m.group("z"))
        return _temp_plan(ctx, int(m.group("n")), True, zone=zs[0] if len(zs) == 1 else None)
    return None


def _nudge_plan(ctx, up, step, zone=None):
    cur = ctx.set_temp()
    if step <= 2:
        acts = [("aircon.nudge", {"delta": step if up else -step})]
        new = None if cur is None else max(16, min(30, int(cur) + (step if up else -step)))
    else:
        if cur is None:
            raise Ambiguous("big step, unknown set")
        new = max(16, min(30, int(cur) + (step if up else -step)))
        acts = [("aircon.set_temp", {"value": new})]
    word = "Warmer" if up else "Cooler"
    reply = f"{word}: {new}°." if new is not None else f"{word}."
    if zone and ctx.zone_on(zone) is not True:
        acts.append(("aircon.zone", {"zone": zone, "on": True}))
        reply = f"{word}: {new}°, {ctx.zone_name(zone)} on." if new is not None else f"{word}, {ctx.zone_name(zone)} on."
    if ctx.ac_power() is False:
        reply += " The aircon is off."
    return Plan(acts, reply)


@rule
def aircon_nudge(t, ctx, o):
    amt = r"(?:(?P<amt>bit|lot) )?"
    warm = r"(?P<d>warmer|hotter|cooler|colder)"
    m = (_m(rf"(?:make |get |turn )?(?:it |house |room |aircon |place )?{amt}{warm}(?: in here| inside| please)?", t)
         or _m(rf"(?:make|get) (?:it )?(?P<z>{ZL_A}) {amt}{warm}", t)
         or _m(rf"(?:make|get) it {amt}{warm} in (?P<z>{ZL_A})", t)
         or _m(rf"(?P<n>\d+) degrees {warm}", t)
         or _m(rf"{warm} by (?P<n>\d+)(?: degrees)?", t)
         or _m(rf"(?:make it )?{amt}{warm} (?P<n>\d+) degrees", t))
    if m:
        up = m.group("d") in ("warmer", "hotter")
        n = m.groupdict().get("n")
        step = int(n) if n else _amount(m.groupdict().get("amt"), 1, 1, 2)
        z = m.groupdict().get("z")
        zs = zones_in(z) if z else []
        if len(zs) > 1:
            raise Ambiguous("several zones warmer")
        return _nudge_plan(ctx, up, step, zs[0] if zs else None)
    m = (_m(rf"(?:turn|bump|put|bring|push|nudge|knock) (?:temp|temperature|heat|heating|thermostat) {amt}(?P<d>up|down)(?: (?:by )?(?P<n>\d+)(?: degrees)?)?", t)
         or _m(rf"(?:turn|bump|bring|push|nudge|knock) (?P<d>up|down) (?:temp|temperature|heat|heating|thermostat)(?: (?:by )?(?P<n>\d+)(?: degrees)?)?", t)
         or _m(rf"(?:temp|temperature) (?P<d>up|down)(?: (?:by )?(?P<n>\d+)(?: degrees)?)?", t)
         or _m(rf"(?:turn it |bump it |take it |go )?(?P<d>up|down) (?P<n>\d+) degrees", t))
    if m:
        up = m.group("d") == "up"
        n = m.groupdict().get("n")
        step = int(n) if n else _amount(m.groupdict().get("amt"), 1, 1, 2)
        return _nudge_plan(ctx, up, step)
    m = _m(r"(?:im|i am|its|it is|were|we are|i feel|feeling|getting)(?: getting)? (?:bit |lot |too |so |really |very |pretty |quite |kind of |kinda )?(?P<f>cold|freezing|chilly|hot|boiling|warm|stuffy|roasting)(?: in here)?", t)
    if m:
        up = m.group("f") in ("cold", "freezing", "chilly")
        return _nudge_plan(ctx, up, 1)
    return None


_MODES = {"cool": "cool", "cooling": "cool", "heat": "heat", "heating": "heat", "heater": "heat", "fan": "fan",
          "fan only": "fan", "dry": "dry", "dehumidify": "dry", "dehumidifier": "dry", "auto": "auto",
          "automatic": "auto"}
_MODE_RE = _alt(_MODES)
_MODE_SAY = {"cool": "Cool mode.", "heat": "Heat mode.", "fan": "Fan only mode.", "dry": "Dry mode.",
             "auto": "Auto mode."}


@rule
def aircon_mode(t, ctx, o):
    m = (_m(rf"(?:aircon |set |put |switch |change |turn )?(?:aircon |it |mode )?(?:to |on |into |onto )?(?P<m>{_MODE_RE}) mode", t)
         or _m(rf"(?:set |change |switch |put )?(?:aircon )?mode (?:to |on |into )?(?P<m>{_MODE_RE})", t)
         or _m(rf"(?:switch|change|set|put) (?:aircon |it )?(?:to|on|onto|over to) (?P<m>cooling|heating|heat|cool|dry|fan only|dehumidify)", t)
         or _m(rf"(?:switch|change|set|put) aircon (?:to|on|onto) (?P<m>{_MODE_RE})", t)
         or _m(r"(?P<m>dehumidify|fan only)(?: house| room| it)?", t)
         or _m(r"(?:turn |switch )?on (?P<m>fan only)", t))
    if not m:
        return None
    mode = _MODES[m.group("m")]
    return Plan([("aircon.mode", {"mode": mode})], _MODE_SAY[mode])


_FANS = {"auto": "auto", "automatic": "auto", "quiet": "quiet", "low": "low", "lowest": "min", "min": "min",
         "minimum": "min", "medium": "medium", "med": "medium", "mid": "medium", "middle": "medium",
         "high": "high", "highest": "max", "max": "max", "maximum": "max", "full": "max", "full blast": "max",
         "powerful": "powerful", "turbo": "turbo"}
_FAN_RE = _alt(_FANS)


@rule
def aircon_fan(t, ctx, o):
    m = (_m(rf"(?:aircon |set |put |turn |change |switch )?(?:aircon )?fan(?: speed)? (?:to |on |at |onto )?(?P<s>{_FAN_RE})(?: speed)?", t)
         or _m(rf"(?P<s>{_FAN_RE}) fan(?: speed)?", t)
         or _m(rf"(?:set |put |turn )?(?:aircon )?fan (?:speed )?(?P<d>up|down)", t)
         or _m(rf"turn (?P<d>up|down) fan(?: speed)?", t))
    if not m:
        return None
    have = ctx.fan_speeds()
    if m.groupdict().get("d"):
        cur = ctx.fan()
        steps = [f for f in have if f != "auto"] or have
        if cur not in steps:
            raise Ambiguous("fan step from auto")
        i = steps.index(cur) + (1 if m.group("d") == "up" else -1)
        speed = steps[max(0, min(len(steps) - 1, i))]
    else:
        speed = _FANS[m.group("s")]
        if speed in ("min", "max"):
            steps = [f for f in have if f != "auto"] or ["low", "high"]
            speed = steps[0] if speed == "min" else steps[-1]
    return Plan([("aircon.fan", {"speed": speed})], f"Fan on {speed}.")


@rule
def aircon_zones_all(t, ctx, o):
    every = r"(?:all|every|all 7|each)"
    rooms = r"(?:vents?|zones?|rooms?|aircon zones?|aircon vents?)"
    m = (_m(rf"(?P<v>open|close|shut|open up) {every} {rooms}", t)
         or _m(rf"(?:turn|switch) (?P<v>on|off) {every} {rooms}", t)
         or _m(rf"(?:turn|switch) {every} {rooms} (?P<v>on|off)", t)
         or _m(rf"{every} {rooms} (?P<v>on|off|open|closed|shut)", t)
         or _m(rf"(?:turn |switch )?(?P<v>on|off) aircon (?:in |for )?{every} rooms", t)
         or _m(rf"aircon (?P<v>on|off) (?:in |for )?{every} rooms", t))
    if not m:
        return None
    on = m.group("v") in ("open", "open up", "on")
    return Plan([("aircon.zones_all", {"on": on})], f"All vents {'open' if on else 'closed'}.")


@rule
def aircon_zone(t, ctx, o):
    anchor = r"(?: aircon| vents?| zones?| air| aircon vents?)"
    patterns = [
        (rf"(?:turn|switch) (?P<v>on|off) (?P<z>{ZL_U})", False),
        (rf"(?:turn|switch) (?P<z>{ZL_U}) (?P<v>on|off)", False),
        (rf"(?P<z>{ZL_U}) (?P<v>on|off)", False),
        (rf"(?:turn|switch) (?P<v>on|off) (?P<z>{ZL_A}){anchor}", False),
        (rf"(?:turn|switch) (?P<z>{ZL_A}){anchor} (?P<v>on|off)", False),
        (rf"(?P<z>{ZL_A}){anchor} (?P<v>on|off|open|closed|shut)", False),
        (rf"(?P<v>open|close|shut|open up) (?:vents? (?:in|for) |aircon (?:in|for) )?(?P<z>{ZL_A})(?:{anchor})?", False),
        (rf"(?:turn|switch) (?P<v>on|off) (?:aircon|air|cooling|heating) (?:in|for|to) (?P<z>{ZL_A})", True),
        (rf"(?:turn |switch )?aircon (?P<v>on|off) (?:in|for) (?P<z>{ZL_A})", True),
        (rf"(?P<v>cool|heat) (?P<z>{ZL_U})", True),
    ]
    for pat, with_power in patterns:
        m = _m(pat, t)
        if not m:
            continue
        v = m.group("v")
        zs = zones_in(m.group("z"))
        if not zs:
            return None
        on = v in ("on", "open", "open up", "cool", "heat")
        acts = []
        if v in ("cool", "heat"):
            acts.append(("aircon.mode", {"mode": v}))
        elif with_power and on and ctx.ac_power() is not True:
            acts.append(("aircon.power", {"on": True}))
        acts += [("aircon.zone", {"zone": z, "on": on}) for z in zs]
        names = _and(ctx.zone_name(z) for z in zs)
        reply = f"{names} {'on' if on else 'off'}."
        if v in ("cool", "heat"):
            reply = f"{'Cooling' if v == 'cool' else 'Heating'} {names}."
        if on and not acts[0][0].startswith("aircon.power") and v not in ("cool", "heat") and ctx.ac_power() is False:
            reply += " The aircon is off."
        return Plan(acts, reply)
    return None


# ----- music

@rule
def music_pause(t, ctx, o):
    if _m(r"(?:pause|stop|hold)(?: music| it| song| track| spotify| playing| playback| that| this| everything)?", t) \
            or _m(r"(?:music|song|spotify) (?:off|stop|pause)", t) \
            or _m(r"(?:turn|switch) (?:off (?:music|spotify)|(?:music|spotify) off)", t) \
            or _m(r"(?:stop|pause) (?:playing )?(?:music|song)", t):
        if t in ("stop", "stop it", "stop that", "stop this") and not ctx.music_playing():
            raise Ambiguous("stop what")
        return Plan([("music.pause", {})], "Paused.")
    return None


@rule
def music_play(t, ctx, o):
    if _m(r"(?:play|resume|unpause|continue|carry on|keep playing|keep going|start)(?: music| it| song| spotify| playing| again| music again)?", t) \
            or _m(r"(?:music|spotify) (?:on|back on|play|resume)", t) \
            or _m(r"(?:turn|switch|put) (?:on )?(?:some )?music(?: on| back on)?", t) \
            or _m(r"(?:play|put on|start) (?:some )?music", t) \
            or _m(r"(?:put|turn) music back on", t):
        if t == "start":
            raise Ambiguous("start what")
        return Plan([("music.play", {})], "Playing.")
    return None


@rule
def music_next(t, ctx, o):
    if _m(r"(?:next|skip)(?: song| track| one| it| this| this song| this one| this track| that| that song)?", t) \
            or _m(r"(?:play |go to |go )?next (?:song|track|one)", t) \
            or _m(r"skip (?:to )?next(?: song| track| one)?", t) \
            or _m(r"(?:change|new) (?:song|track)", t):
        return Plan([("music.next", {})], "Next song.")
    return None


@rule
def music_previous(t, ctx, o):
    if _m(r"(?:previous|prev|back)(?: song| track| one)?", t) \
            or _m(r"(?:go|skip|jump) back(?: 1| one)?(?: song| track)?", t) \
            or _m(r"(?:play |go to )?(?:previous|last) (?:song|track|one)(?: again)?", t) \
            or _m(r"(?:restart|replay) (?:song|track|this song|this track|it|that)", t) \
            or _m(r"(?:play|start) (?:song|this song|that song|that|it) again", t):
        return Plan([("music.previous", {})], "Going back.")
    return None


def _speaker_target(ctx, ids, reply):
    ids = [s for s in SPEAKER_NAMES if s in ids]
    return Plan([("music.speakers", {"speakers": ids})], reply)


@rule
def music_speakers(t, ctx, o):
    verbs = r"(?:play|put|move|switch|send|have|stream|cast|resume|start|turn on|change)"
    what = r"(?: music| it| this| song| spotify| this song| that)?"
    prep = r"(?:in|on|to|through|onto|into|over to|out)"
    names = lambda ids: _and(SPEAKER_NAMES[s] for s in SPEAKER_NAMES if s in ids)
    # everywhere
    if _m(rf"(?:{verbs}{what} )?(?:{prep} )?{EVERYWHERE}", t) or _m(rf"(?:music|play|playing){what} {EVERYWHERE}", t):
        return _speaker_target(ctx, list(SPEAKER_NAMES), "Playing on all three speakers.")
    # only / just
    m = _m(rf"(?:play |music )?(?:only|just) (?:{prep} |play {prep} )?(?P<l>{SL_A})", t) or \
        _m(rf"{verbs}{what} (?:only|just) {prep} (?P<l>{SL_A})", t)
    if m:
        ids = speakers_in(m.group("l"))
        return _speaker_target(ctx, ids, f"Playing only in {names(ids)}.")
    # add
    m = (_m(rf"(?:add|also play {prep}|also {prep}|play {prep}|put music {prep}|turn on) (?P<l>{SL_A})(?: speakers?)? (?:too|as well)", t)
         or _m(rf"(?:add|also play {prep}|also {prep}) (?P<l>{SL_A})(?: speakers?)?(?: too| as well)?", t)
         or _m(rf"(?:turn|switch) on (?P<l>{SL_A}) speakers?", t))
    if m:
        new = speakers_in(m.group("l"))
        if not ctx.now():
            return _speaker_target(ctx, new, f"Playing in {names(new)}.")
        ids = list(dict.fromkeys(ctx.speakers_in_use() + new))
        return _speaker_target(ctx, ids, f"Added {names(new)}.")
    # remove
    m = (_m(rf"(?:stop|turn off|switch off|mute) (?:music |playing )?(?:in |on |from )?(?P<l>{SL_A}) speakers?", t)
         or _m(rf"(?:stop|turn off|switch off) (?:music|playing) (?:in |on |from )?(?P<l>{SL_A})", t)
         or _m(rf"(?:stop|turn off|switch off) (?:in |on )?(?P<l>{SL_U})", t)
         or _m(rf"(?P<l>{SL_A}) speakers? off", t))
    if m:
        gone = speakers_in(m.group("l"))
        ids = [s for s in ctx.speakers_in_use() if s not in gone]
        if not ids:
            return Plan([("music.pause", {})], "Paused.")
        return _speaker_target(ctx, ids, f"Stopped in {names(gone)}.")
    # move / play in
    m = (_m(rf"{verbs}{what} {prep} (?P<l>{SL_A})(?: speakers?| too)?", t)
         or _m(rf"(?:music|playing){what} {prep} (?P<l>{SL_A})", t)
         or _m(rf"(?:play|music) (?P<l>{SL_U})", t))
    if m:
        ids = speakers_in(m.group("l"))
        return _speaker_target(ctx, ids, f"Playing in {names(ids)}.")
    return None


def _speaker_volume_plan(ctx, ids, up, step):
    acts = []
    for s in ids:
        cur = ctx.speaker_volume(s)
        if not isinstance(cur, int):
            raise Ambiguous("speaker volume unknown")
        acts.append(("speakers.volume", {"speaker": s, "value": max(0, min(100, cur + (step if up else -step)))}))
    if not acts:
        return Plan([], "Nothing is playing on the speakers.")
    return Plan(acts, "Music louder." if up else "Music quieter.")


@rule
def music_volume(t, ctx, o):
    spk_words = r"(?:music|speakers?|spotify|song)"
    one = rf"(?:{_spk_one(False)}|{_alt([w for ws in SPK_SHARED.values() for w in ws])} speakers?)"
    m = (_m(rf"(?:set |turn |put |change )?(?P<w>{spk_words}|{one})(?: volume)? (?:to|at|on|up to|down to) (?P<n>\d+)", t)
         or _m(rf"(?:set |turn |put |change )?volume (?:of|on|for|in) (?P<w>{spk_words}|{one}) (?:to|at) (?P<n>\d+)", t)
         or _m(rf"turn (?P<w>{spk_words}|{one}) (?:up|down) to (?P<n>\d+)", t))
    if m:
        n = int(m.group("n"))
        if not 0 <= n <= 100:
            return Plan([], "Speaker volume goes from 0 to 100.")
        ids = speakers_in(m.group("w"))
        if not ids:
            return Plan([("speakers.volume", {"speaker": "all", "value": n})], f"Speakers at {n}.")
        return Plan([("speakers.volume", {"speaker": s, "value": n}) for s in ids],
                    f"{_and(SPEAKER_NAMES[s] for s in ids)} at {n}.")
    amt = r"(?:(?P<amt>bit|lot) )?"
    m = (_m(rf"(?:make |turn )?(?P<w>{spk_words}|{one}) {amt}(?P<d>louder|quieter|softer|up|down|lower|higher)", t)
         or _m(rf"turn (?P<d>up|down) (?P<w>{spk_words}|{one})", t)
         or _m(rf"turn (?P<w>{spk_words}|{one}) {amt}(?P<d>up|down)", t))
    if m:
        up = m.group("d") in ("louder", "up", "higher")
        step = _amount(m.groupdict().get("amt"), 5, 10, 20)
        ids = speakers_in(m.group("w")) or ctx.speakers_in_use()
        return _speaker_volume_plan(ctx, ids, up, step)
    return None


@rule
def bare_volume(t, ctx, o):
    """"louder", "volume down", "volume to 20": the speakers or the TV, whichever is the only one going."""
    amt = r"(?:(?P<amt>bit|lot) )?"
    m = (_m(rf"(?:make it |turn it )?{amt}(?P<d>louder|quieter|softer)", t)
         or _m(r"(?:turn )?volume (?P<d>up|down)", t)
         or _m(r"turn (?P<d>up|down) volume", t)
         or _m(r"(?:set )?volume (?:to|at) (?P<n>\d+)", t))
    if not m:
        return None
    music = ctx.music_playing()
    tvs = ctx.tvs_on()
    if music and not tvs:
        target = "speakers"
    elif tvs and not music and len(tvs) == 1:
        target = "tv"
    else:
        raise Ambiguous("louder: what")
    if m.groupdict().get("n"):
        n = int(m.group("n"))
        if target == "speakers":
            if not 0 <= n <= 100:
                raise Ambiguous("volume range")
            return Plan([("speakers.volume", {"speaker": "all", "value": n})], f"Speakers at {n}.")
        return tv_volume(f"{TV_REF[tvs[0]][0]} volume to {n}", ctx, o)
    up = m.group("d") in ("louder", "up")
    if target == "speakers":
        return _speaker_volume_plan(ctx, ctx.speakers_in_use(), up, _amount(m.groupdict().get("amt"), 5, 10, 20))
    step = _amount(m.groupdict().get("amt"), 2, 3, 6)
    tv = tvs[0]
    return Plan([("tv.volume", {"tv": tv, "delta": step if up else -step})],
                f"{ctx.tv_label(tv)} {'louder' if up else 'quieter'}.", tv=tv)


@rule
def search_play(t, ctx, o):
    m = (_m(rf"(?P<verb>play|put on|start|stream|shuffle) (?P<q>.+?) (?:in|on|through|out) (?P<l>{SL_A}|{EVERYWHERE})(?: speakers?)?", t)
         or _m(r"(?P<verb>play|put on|shuffle|stream) (?P<q>.+?)", t)
         or _m(r"(?P<verb>put) (?P<q>.+?) on", t))
    if not m:
        return None
    raw = m.group("q")
    hint = _music_hint(raw) or "spotify" in t
    q = _clean_free(raw)
    if not q or re.match(r"(?:in|on|to|at|some|it)\b", q):
        raise Ambiguous("vague query")
    apps = _app_words(ctx)
    if q in apps or re.search(rf"\b(?:{_app_re(ctx)}|tv)\b", raw):
        raise Ambiguous("tv words in a music query")
    loc = m.groupdict().get("l")
    args = {"query": _title_case(q, o)}
    where = ""
    if loc:
        ids = list(SPEAKER_NAMES) if re.fullmatch(EVERYWHERE, loc) else speakers_in(loc)
        shared_only = all(s in SPK_SHARED for s in ids)
        if shared_only and not hint:
            raise Ambiguous("lounge: tv or speaker")
        args["speakers"] = [s for s in SPEAKER_NAMES if s in ids]
        where = " in " + _and(SPEAKER_NAMES[s] for s in args["speakers"])
    else:
        verb = m.group("verb")
        tvs_on = ctx.tvs_on()
        if verb in ("put on", "put") and not hint:
            # "put on Bluey": a show, if one TV is the obvious place
            if len(tvs_on) == 1 or ctx.last_tv:
                return tv_play(f"put on {q} on {TV_REF[ctx.pick_tv()][0]}", ctx, o)
            raise Ambiguous("put on what where")
        if tvs_on and not hint and not ctx.music_playing():
            raise Ambiguous("play: tv is on, music or show?")
    return Plan([("music.search_play", args)], f"Playing {args['query']}{where}.")


# ---------------------------------------------------------------- entry point

_SPLIT = re.compile(r"\s*(?:,\s*(?:and\s+(?:then\s+)?|then\s+)?|\band then\b|\bthen\b|\band also\b|\balso\b|\band\b|\bplus\b)\s*")


def _clause(t, ctx, original):
    for r in RULES:
        res = r(t, ctx, original)
        if res is not None:
            return res
    return None


def _seq(t, ctx, original, depth=0):
    """The whole sentence as one clause, or split at 'and'/'then'/commas into clauses that all parse."""
    if depth > 4:
        return None
    try:
        whole = _clause(t, ctx, original)
    except Ambiguous:
        whole = None
        if depth == 0 and not _SPLIT.search(t):
            raise
    if whole is not None:
        return whole
    for m in _SPLIT.finditer(t):
        left, right = t[:m.start()].strip(), t[m.end():].strip()
        if not left or not right:
            continue
        try:
            lp = _clause(left, ctx, original)
        except Ambiguous:
            continue
        if lp is None or not lp.actions:
            continue
        try:
            rp = _seq(right, ctx.after(lp), original, depth + 1)
        except Ambiguous:
            rp = None
        if rp is not None and rp.actions:
            return lp + rp
    return None


def parse(text: str, state: dict | None = None) -> Plan | None:
    """The fast path. A Plan (actions + reply) or None for 'ask Claude'."""
    t = normalize(text)
    if not t or len(t) > 200:
        return None
    words = t.split()
    if words[0] in _QUESTION_START or any(w in _GUARD for w in words):
        return None
    try:
        plan = _seq(t, Ctx(state), text)
    except Ambiguous:
        return None
    if plan is None or len(plan.actions) > 6:
        return None
    return plan
