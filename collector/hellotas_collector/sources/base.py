"""What every source adapter gets to work with."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from ..fetch import Fetcher
from ..model import RawEvent


@dataclass
class Context:
    fetcher: Fetcher
    tz: ZoneInfo
    now: datetime
    # True for links not worth opening again: archived (past) events, rejected or ignored ones
    skip_url: Callable[[str], bool] = lambda url: False
    # Reads a page with no structured data: (page text, page url, source id) -> events. None without AI.
    read_page: Callable[[str, str, str], list[RawEvent]] | None = None
    notes: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.notes.append(message)


def apply_defaults(ev: RawEvent, cfg: dict) -> RawEvent:
    """Fill gaps from the source's `defaults` and drop pictures matching `image_exclude`."""
    defaults = cfg.get("defaults") or {}
    if not ev.host and defaults.get("host"):
        ev.host = defaults["host"]
    if not ev.region and defaults.get("region") and not ev.online:
        ev.region = defaults["region"]
    ev.extra.setdefault("default_topics", list(defaults.get("topics") or []))
    if defaults.get("type"):
        ev.extra.setdefault("default_type", defaults["type"])
    ev.extra.setdefault("trust", cfg.get("trust", "medium"))
    excluded = cfg.get("image_exclude") or []
    ev.images = [u for u in dict.fromkeys(ev.images) if u and not any(x in u for x in excluded)]
    return ev


def follow_rx(cfg: dict) -> re.Pattern | None:
    return re.compile(cfg["follow"]) if cfg.get("follow") else None
