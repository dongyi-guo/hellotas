"""Turning any event page into a RawEvent: structured data first, then the registration link, then the AI."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from ..extract import event_from_jsonld, jsonld_event_objects, meta, registration_links
from ..fetch import Blocked, FetchError, Page
from ..model import RawEvent
from ..text import html_to_text, url_key
from .base import Context, apply_defaults

# Sites whose terms forbid automated access: never fetched; people paste the text instead
NO_FETCH_HOSTS = ("linkedin.com", "lnkd.in", "facebook.com", "fb.me", "instagram.com", "x.com", "twitter.com")

_MONTH = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
_MON = "|".join(_MONTH)
_DAY_MONTH_YEAR = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})[a-z]*\.?,?\s+(\d{{4}})\b", re.I)
_MONTH_DAY_YEAR = re.compile(rf"\b({_MON})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_SLASHED = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")  # Australian order: day/month/year
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def is_no_fetch(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in NO_FETCH_HOSTS)


def dates_in(text: str) -> list[tuple[int, int, int]]:
    """(year, month, day) for every date written in a common format."""
    candidates = []
    candidates += [(int(y), _MONTH[mon.lower()[:3]], int(d)) for d, mon, y in _DAY_MONTH_YEAR.findall(text)]
    candidates += [(int(y), _MONTH[mon.lower()[:3]], int(d)) for mon, d, y in _MONTH_DAY_YEAR.findall(text)]
    candidates += [(int(y), int(mo), int(d)) for d, mo, y in _SLASHED.findall(text)]
    candidates += [(int(y), int(mo), int(d)) for y, mo, d in _ISO.findall(text)]
    found = []
    for y, mo, d in candidates:
        try:
            datetime(y, mo, d)
        except ValueError:
            continue
        found.append((y, mo, d))
    return found


def mentions_upcoming_date(text: str, now: datetime) -> bool:
    """True if the text names at least one date from today on. Saves an AI call on pages about past events."""
    today = (now.year, now.month, now.day)
    return any(d >= today for d in dates_in(text))


def from_structured(page: Page, source: str, ctx: Context) -> RawEvent | None:
    objs = jsonld_event_objects(page.text)
    if not objs:
        return None
    here = url_key(page.url)
    obj = next((o for o in objs if o.get("url") and url_key(str(o["url"])) == here), objs[0])
    ev = event_from_jsonld(obj, page.url, source, ctx.tz)
    if not ev.images:
        og = meta(page.text).get("og:image")
        ev.images = [og] if og else []
    return ev


def resolve_page(page: Page, source: str, ctx: Context, cfg: dict | None = None,
                 pasted_text: str = "") -> list[RawEvent]:
    """Events described by a fetched page (usually one). Empty when nothing reliable could be read."""
    cfg = cfg or {"id": source}
    ev = from_structured(page, source, ctx)
    if ev:
        return [apply_defaults(ev, cfg)]
    # A page without event data that links to a ticketing page that has it ("Register here")
    for link in registration_links(page.text, page.url)[:2]:
        if ctx.skip_url(link):
            continue
        try:
            ticket_page = ctx.fetcher.get(link)
        except (Blocked, FetchError) as exc:
            ctx.note(f"{link}: {exc}")
            continue
        ev = from_structured(ticket_page, source, ctx)
        if ev:
            ev.extra["listing_page"] = page.url
            if not ev.images:
                og = meta(page.text).get("og:image")
                ev.images = [og] if og else []
            return [apply_defaults(ev, cfg)]
    text = html_to_text(page.text, limit=30000)
    if pasted_text:
        text = pasted_text + "\n\n---\nText of the page:\n" + text
    return read_with_ai(text, page.url, source, ctx, cfg, og_image=meta(page.text).get("og:image", ""))


def read_with_ai(text: str, url: str, source: str, ctx: Context, cfg: dict | None = None,
                 og_image: str = "") -> list[RawEvent]:
    cfg = cfg or {"id": source}
    if not mentions_upcoming_date(text, ctx.now):
        ctx.note(f"{url}: no upcoming date mentioned, not read")
        return []
    if ctx.read_page is None:
        ctx.note(f"{url}: no structured event data; set ANTHROPIC_API_KEY to let the AI read pages like this")
        return []
    events = ctx.read_page(text, url, source)
    for ev in events:
        if og_image and not ev.images:
            ev.images = [og_image]
        apply_defaults(ev, cfg)
    return events


def resolve_url(url: str, ctx: Context, source: str = "suggestion", pasted_text: str = "") -> list[RawEvent]:
    """For a link someone suggested. Never fetches sites that forbid automated access; uses pasted text there."""
    if is_no_fetch(url):
        if not pasted_text.strip():
            raise FetchError(
                f"{urlsplit(url).hostname} doesn't allow automated access, so the collector can't open this link. "
                "Paste the post's text into the form (or link the event's registration page instead).")
        return read_with_ai(pasted_text, url, source, ctx)
    try:
        page = ctx.fetcher.get(url)
    except Blocked:
        if pasted_text.strip():
            return read_with_ai(pasted_text, url, source, ctx)
        raise
    return resolve_page(page, source, ctx, pasted_text=pasted_text)
