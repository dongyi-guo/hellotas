"""A listing page whose event pages carry schema.org Event data (GDG/Bevy, Meetup, Humanitix, Eventbrite)."""

from __future__ import annotations

from ..extract import event_from_jsonld, jsonld_event_objects, links, links_in_text, meta, page_images
from ..fetch import Blocked, FetchError
from ..model import RawEvent
from ..text import url_key
from .base import Context, apply_defaults, follow_rx


def read_event_page(url: str, cfg: dict, ctx: Context) -> RawEvent | None:
    """The event described on one page, or None when the page has no Event data."""
    page = ctx.fetcher.get(url)
    objs = jsonld_event_objects(page.text)
    if not objs:
        return None
    # Prefer the Event whose url is this page (Meetup pages also describe related events)
    here = url_key(page.url)
    obj = next((o for o in objs if o.get("url") and url_key(str(o["url"])) == here), objs[0])
    ev = event_from_jsonld(obj, page.url, cfg["id"], ctx.tz)
    if not ev.url or url_key(ev.url) != url_key(page.url):
        ev.url = page.url
    if cfg.get("page_images"):
        ev.images = page_images(page.text, page.url, cfg["page_images"]) + ev.images
    # The page's sharing picture as a last resort: it often lives on another host, with its own robots.txt
    og = meta(page.text).get("og:image")
    if og and og not in ev.images:
        ev.images.append(og)
    return ev


def collect(cfg: dict, ctx: Context) -> list[RawEvent]:
    listing = ctx.fetcher.get(cfg["listing"])
    rx = follow_rx(cfg)
    # Events described on the listing itself (Eventbrite search pages list them as an ItemList)
    listed = {}
    for obj in jsonld_event_objects(listing.text):
        ev = event_from_jsonld(obj, listing.url, cfg["id"], ctx.tz)
        if ev.url:
            listed[ev.url] = ev
    urls = links(listing.text, listing.url, cfg.get("follow"))
    if cfg.get("follow"):
        urls += [u for u in links_in_text(listing.text, cfg["follow"]) if u not in urls]
    urls += [u for u in listed if u not in urls and (rx is None or rx.search(u))]

    events: list[RawEvent] = []
    for url in urls[: int(cfg.get("max_events", 15))]:
        if ctx.skip_url(url):
            continue
        try:
            ev = read_event_page(url, cfg, ctx)
        except Blocked as exc:
            ctx.note(f"{url}: {exc}")
            continue
        except FetchError as exc:
            ctx.note(f"{url}: {exc}")
            ev = None
        if ev is None:
            ev = listed.get(url)  # fall back to what the listing said
        if ev is not None:
            events.append(apply_defaults(ev, cfg))
    return events
