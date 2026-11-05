"""Telling a Discord channel about newly published events (upstream issue #63: supervisors sharing info with
students). Run after a deploy with the site's events.json from before and after; it posts only events that are new.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import requests


def new_events(old: dict | None, new: dict) -> list[dict]:
    before = {e["id"] for e in (old or {}).get("events", [])}
    return [e for e in new.get("events", []) if e["id"] not in before]


def _embed(e: dict) -> dict:
    when = e.get("start", "")
    try:
        dt = datetime.fromisoformat(when)
        when_text = dt.strftime("%a %-d %b %Y") + ("" if e.get("all_day") else dt.strftime(", %-I:%M %p").lower())
        when_text += " (Hobart time)"
    except ValueError:
        when_text = when
    where = "Online" if e.get("format") == "online" else (e.get("location") or "")
    embed = {
        "title": e.get("title", "")[:250],
        "url": e.get("page") or e.get("url"),
        "description": (e.get("summary") or "")[:600],
        "color": 0xC8102E,
        "fields": [{"name": "When", "value": when_text[:1000], "inline": True}],
    }
    if where:
        embed["fields"].append({"name": "Where", "value": where[:1000], "inline": True})
    if e.get("cost"):
        embed["fields"].append({"name": "Cost", "value": e["cost"][:1000], "inline": True})
    if e.get("image"):
        embed["image"] = {"url": e["image"]}
    return embed


def post(webhook_url: str, events: list[dict], session: requests.Session | None = None) -> int:
    """Posts up to 10 events per message. Returns how many were posted."""
    http = session or requests.Session()
    posted = 0
    for i in range(0, len(events), 10):
        chunk = events[i:i + 10]
        body = {"embeds": [_embed(e) for e in chunk], "allowed_mentions": {"parse": []}}
        if posted == 0:
            body["content"] = "New on Tasmania Welcome:"
        for _attempt in range(3):
            resp = http.post(webhook_url, json=body, timeout=20)
            if resp.status_code == 429:
                time.sleep(float(resp.json().get("retry_after", 2)))
                continue
            resp.raise_for_status()
            posted += len(chunk)
            break
    return posted


def load(path: str | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
