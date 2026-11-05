"""The site's own event list (happening/index.json, built by Hugo), so the API never disagrees with the site.

Fetched from SITE_URL and refreshed every ten minutes. If a refresh fails, the last good copy is kept.
A file path works too (used by the tests and for local development).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import requests


class EventFeed:
    def __init__(self, url_for_lang, refresh_seconds: int = 600, session: requests.Session | None = None):
        self.url_for_lang = url_for_lang
        self.refresh_seconds = refresh_seconds
        self.http = session or requests.Session()
        self.http.headers["User-Agent"] = "hellotas-api/1.0"
        self._cache: dict[str, tuple[float, dict[str, dict]]] = {}
        self._lock = threading.Lock()

    def _load(self, lang: str) -> dict[str, dict]:
        url = self.url_for_lang(lang)
        if url.startswith(("http://", "https://")):
            resp = self.http.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        else:
            data = json.loads(Path(url).read_text(encoding="utf-8"))
        return {e["id"]: e for e in data.get("events", []) if e.get("id")}

    def events(self, lang: str = "en") -> dict[str, dict]:
        lang = lang if lang in ("en", "zh", "ne") else "en"
        with self._lock:
            cached = self._cache.get(lang)
            if cached and time.monotonic() - cached[0] < self.refresh_seconds:
                return cached[1]
        try:
            events = self._load(lang)
        except (requests.RequestException, OSError, ValueError, KeyError):
            if cached:
                return cached[1]
            if lang != "en":
                return self.events("en")
            return {}
        with self._lock:
            self._cache[lang] = (time.monotonic(), events)
        return events

    def get(self, event_id: str, lang: str = "en") -> dict | None:
        return self.events(lang).get(event_id)
