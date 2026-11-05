"""The Australian Computer Society's national event list.

The ACS events page loads its list from a JSON file (data-source on the page); each event also has a server-rendered
detail page with prices and the full description. Online events are open to anyone in Australia, so they are kept
from every state; in-person ones only from the states in the config (Tasmania).
"""

from __future__ import annotations

import json
import re

from ..extract import parse_when
from ..fetch import Blocked, FetchError
from ..model import RawEvent
from ..text import clean, clean_title, html_to_text
from .base import Context, apply_defaults

_PRICE = re.compile(r"^(Member|Member-Concessional|Non-Member|Student|Guest)\s*\$\s*([\d,]+(?:\.\d\d)?)$", re.I)


def detail_facts(markup: str) -> dict:
    """Prices and the 'About this event' text from an ACS event page."""
    lines = html_to_text(markup).splitlines()
    prices = {}
    for line in lines:
        m = _PRICE.match(line.strip())
        if m:
            prices[m.group(1).lower()] = float(m.group(2).replace(",", ""))
    about = []
    if "About this event" in lines:
        for line in lines[lines.index("About this event") + 1:]:
            if line in ("Key Takeaways", "Speakers", "Speaker", "Share this event"):
                break
            about.append(line)
    # Speaker names are split over lines on the page ("Join", "Alannah Grech", ",", "Student and ..."); rejoin
    text = re.sub(r"\s+([,.])", r"\1", " ".join(about))
    return {"prices": prices, "about": clean(text)}


def describe_cost(prices: dict) -> tuple[str, bool | None]:
    if not prices:
        return "", None
    member = prices.get("member")
    non_member = prices.get("non-member")
    if all(v == 0 for v in prices.values()):
        return "Free", True
    if member == 0 and non_member:
        return f"Free for ACS members · ${non_member:,.0f} for non-members", False
    if member is not None and non_member is not None:
        return f"${member:,.0f} for ACS members · ${non_member:,.0f} for non-members", False
    lo = min(prices.values())
    return f"From ${lo:,.0f}", False


def collect(cfg: dict, ctx: Context) -> list[RawEvent]:
    page = ctx.fetcher.get(cfg["listing"], accept="application/json")
    data = json.loads(page.text)
    states = set(cfg.get("states") or [])
    exclude_types = set(cfg.get("exclude_types") or [])
    exclude_titles = re.compile(cfg["exclude_titles"]) if cfg.get("exclude_titles") else None

    events = []
    for item in data.get("events", []):
        title = clean_title(item.get("eventTitle", ""))
        virtual = bool(item.get("eventIsVirtual"))
        state = (item.get("eventState") or "").upper()
        if not virtual and state not in states:
            continue
        if item.get("eventType") in exclude_types:
            continue
        if exclude_titles and exclude_titles.search(title):
            continue
        if cfg.get("skip_member_only") and str(item.get("memberOnlyEvent")).lower() == "true":
            continue
        url = f"{cfg['detail_url']}?eventId={item['eventId']}"
        start, _ = parse_when(item.get("eventStartDateUTC"), ctx.tz)
        end, _ = parse_when(item.get("eventEndDateUTC"), ctx.tz)
        ev = RawEvent(
            source=cfg["id"], url=url, title=title, start=start, end=end,
            description=clean(item.get("description")),
            online=virtual, attendance="online" if virtual else "in_person",
            location_name="" if virtual else clean(item.get("eventVenue")),
            address="" if virtual else ", ".join(p for p in (clean(item.get("eventStreet")), clean(
                item.get("eventCity")), state) if p),
            locality=clean(item.get("eventCity")), region="" if virtual else state,
            host="ACS Tasmania" if state == "TAS" and not virtual else "ACS",
            images=[item["eventImageUrl"]] if item.get("eventImageUrl") else [],
            extra={"acs_type": item.get("eventType", ""), "cpd_hours": item.get("cpdHours", ""),
                   "delivery": item.get("deliveryMethod", "")},
        )
        events.append(apply_defaults(ev, cfg))

    # Detail pages only for events not archived or rejected: prices and the full description
    for ev in events:
        if ctx.skip_url(ev.url):
            continue
        try:
            facts = detail_facts(ctx.fetcher.get(ev.url).text)
        except (Blocked, FetchError) as exc:
            ctx.note(f"{ev.url}: {exc}")
            continue
        ev.cost, ev.free = describe_cost(facts["prices"])
        if len(facts["about"]) > len(ev.description):
            ev.extra["short_description"] = ev.description
            ev.description = facts["about"]
    return events
