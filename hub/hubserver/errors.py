"""Errors that become plain-words answers. Every message is safe to show a person."""


class HubError(Exception):
    """An answer that is not ok. status is the HTTP status, extra goes into the JSON."""

    def __init__(self, status, text, **extra):
        super().__init__(text)
        self.status = status
        self.text = text
        self.extra = extra


DEVICE_DOWN_TEXT = {
    "aircon": "The aircon is not answering.",
    "speakers": "The speakers are not answering.",
    "tvs": "The TV bridge is not answering.",
}


class DeviceDown(HubError):
    def __init__(self, device, text=None):
        super().__init__(503, text or DEVICE_DOWN_TEXT[device], device=device)
        self.device = device


class NothingPlaying(HubError):
    def __init__(self):
        super().__init__(409, "Nothing is playing. Start some music first.")


class NeedsSpotify(HubError):
    def __init__(self, text="Spotify is not linked yet."):
        super().__init__(409, text, needs="spotify")


class Conflict(HubError):
    def __init__(self, text):
        super().__init__(409, text)


class TvOff(HubError):
    def __init__(self, name):
        bare = name[4:] if name.lower().startswith("the ") else name
        super().__init__(409, f"The {bare} TV is off. Turn it on first.")
