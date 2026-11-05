"""A listing of event pages that carry no structured data (TasICT)."""

from __future__ import annotations

from ..extract import links
from ..fetch import Blocked, FetchError
from ..model import RawEvent
from .base import Context
from .page import resolve_page


def collect(cfg: dict, ctx: Context) -> list[RawEvent]:
    listing = ctx.fetcher.get(cfg["listing"])
    events: list[RawEvent] = []
    for url in links(listing.text, listing.url, cfg.get("follow"))[: int(cfg.get("max_events", 12))]:
        if ctx.skip_url(url):
            continue
        try:
            page = ctx.fetcher.get(url)
        except (Blocked, FetchError) as exc:
            ctx.note(f"{url}: {exc}")
            continue
        events.extend(resolve_page(page, cfg["id"], ctx, cfg))
    return events
