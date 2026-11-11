#!/usr/bin/env python3
"""A stand-in for the `claude` CLI, for unit tests. Never calls anything.

FAKE_CLAUDE_MODE picks the answer; FAKE_CLAUDE_RECORD (a file) gets what it was called with.
"""
import json
import os
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
prompt = sys.stdin.read()
rec = os.environ.get("FAKE_CLAUDE_RECORD")
if rec:
    with open(rec, "w") as f:
        json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(), "cwd_files": os.listdir("."),
                   "env_keys": sorted(os.environ), "prompt": prompt}, f)


def result(text, **extra):
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text, **extra}))


ANSWERS = {
    "ok": {"reply": "Cosy movie mode: lounge warmer and the TV on.",
           "actions": [{"action": "aircon.zone", "args": {"zone": "living", "on": True}},
                       {"action": "aircon.nudge", "args": {"delta": 1}},
                       {"action": "tv.power", "args": {"tv": "living-room", "on": True}}]},
    "bad_actions": {"reply": "Done.",
                    "actions": [{"action": "system.exec", "args": {"cmd": "rm -rf /"}},
                                {"action": "aircon.set_temp", "args": {"value": 99}},
                                {"action": "aircon.zone", "args": {"zone": "garage", "on": True}},
                                {"action": "music.pause", "args": {}},
                                "not an object"]},
    "too_many": {"reply": "Lots.", "actions": [{"action": "aircon.nudge", "args": {"delta": 1}}] * 8},
    "refuse": {"reply": "Sorry, I can only help with the aircon, music and TVs.", "actions": []},
}

if mode == "sleep":
    time.sleep(30)
    result("{}")
elif mode == "fenced":
    result("```json\n" + json.dumps(ANSWERS["ok"]) + "\n```")
elif mode == "prose":
    result("Sorry, I can't help with that.")
elif mode == "garbage":
    result("{not json at all " * 30)
elif mode == "is_error":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in"}))
elif mode == "crash":
    sys.stderr.write("boom\n")
    sys.exit(1)
else:
    result(json.dumps(ANSWERS[mode]))
