"""Reading event facts out of pages: schema.org JSON-LD, Open Graph tags and links."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .model import RawEvent
from .text import clean, clean_title, html_to_text

# schema.org Event and its subtypes
_EVENT_TYPES = {
    "Event", "BusinessEvent", "ChildrensEvent", "ComedyEvent", "CourseInstance", "DanceEvent", "DeliveryEvent",
    "EducationEvent", "EventSeries", "ExhibitionEvent", "Festival", "FoodEvent", "Hackathon", "LiteraryEvent",
    "MusicEvent", "PublicationEvent", "SaleEvent", "ScreeningEvent", "SocialEvent", "SportsEvent",
    "TheaterEvent", "VisualArtsEvent",
}

# Hosts whose event pages carry JSON-LD, worth following from a page that has none (e.g. a "Register here" link)
STRUCTURED_HOSTS = (
    "humanitix.com", "eventbrite.com", "eventbrite.com.au", "meetup.com", "gdg.community.dev", "lu.ma",
    "trybooking.com", "tickettailor.com",
)

_AU_STATES = {
    "tas": "TAS", "tasmania": "TAS", "vic": "VIC", "victoria": "VIC", "nsw": "NSW", "new south wales": "NSW",
    "qld": "QLD", "queensland": "QLD", "sa": "SA", "south australia": "SA", "wa": "WA",
    "western australia": "WA", "nt": "NT", "northern territory": "NT", "act": "ACT",
    "australian capital territory": "ACT",
}
_TAS_PLACES = re.compile(
    r"\b(hobart|launceston|burnie|devonport|sandy bay|inveresk|newnham|cradle coast|glenorchy|kingston|"
    r"bellerive|rosny|sorell|moonah|new town|north hobart|battery point|salamanca|ulverstone|tasmania)\b", re.I)


def _types(obj: dict) -> set[str]:
    t = obj.get("@type", [])
    return set(t if isinstance(t, list) else [t])


def _walk(node):
    """Every dict inside a JSON-LD document (handles @graph, lists and ItemList entries)."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "itemListElement", "item", "subEvent", "event"):
            if key in node:
                yield from _walk(node[key])


def jsonld_blocks(markup: str) -> list:
    soup = BeautifulSoup(markup, "lxml")
    out = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw, strict=False))
        except json.JSONDecodeError:
            # Some sites leave trailing commas; one forgiving retry
            try:
                out.append(json.loads(re.sub(r",\s*([}\]])", r"\1", raw), strict=False))
            except json.JSONDecodeError:
                continue
    return out


def jsonld_event_objects(markup: str) -> list[dict]:
    events = []
    for block in jsonld_blocks(markup):
        for obj in _walk(block):
            if _types(obj) & _EVENT_TYPES and obj.get("name"):
                events.append(obj)
    return events


def parse_when(value, tz: ZoneInfo) -> tuple[datetime | None, bool]:
    """(aware datetime, date_only) from an ISO 8601 string. Times without an offset are taken as local."""
    if not value:
        return None, False
    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        d = date.fromisoformat(s)
        return datetime.combine(d, time(0, 0), tz), True
    s = s.replace("Z", "+00:00")
    # 2026-11-09T17:30:00+1100 -> +11:00 (fromisoformat handles both on 3.11+, this keeps 3.10-era data safe)
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None, False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz), False


def _name(v) -> str:
    if isinstance(v, list):
        return ", ".join(n for n in (_name(x) for x in v) if n)
    if isinstance(v, dict):
        return clean(v.get("name") or v.get("legalName") or "")
    return clean(v) if isinstance(v, str) else ""


def _images(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [u for u in [v.get("url") or v.get("contentUrl")] if u]
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(_images(x))
        return out
    return []


def _region(text: str) -> str:
    low = clean(text).lower().strip(" .")
    if low in _AU_STATES:
        return _AU_STATES[low]
    m = re.search(r"\b(TAS|VIC|NSW|QLD|SA|WA|NT|ACT)\b\s*\d{0,4}", text or "")
    if m:
        return m.group(1)
    m = re.search(r"\b([0-9]{4})\b", text or "")
    if m and m.group(1).startswith("7"):
        return "TAS"
    return "TAS" if _TAS_PLACES.search(text or "") else ""


def event_from_jsonld(obj: dict, page_url: str, source: str, tz: ZoneInfo) -> RawEvent:
    start, date_only = parse_when(obj.get("startDate"), tz)
    end, end_date_only = parse_when(obj.get("endDate"), tz)
    ev = RawEvent(source=source, url=clean(obj.get("url")) or page_url, title=clean_title(obj.get("name", "")),
                  start=start, end=end, all_day=date_only and (end is None or end_date_only))
    if ev.url and not ev.url.startswith("http"):
        ev.url = urljoin(page_url, ev.url)
    desc = obj.get("description") or ""
    ev.description = html_to_text(desc) if "<" in desc else clean(desc)

    mode = str(obj.get("eventAttendanceMode", ""))
    if "Mixed" in mode:
        ev.attendance = "hybrid"
    elif "Online" in mode:
        ev.attendance = "online"
    elif "Offline" in mode:
        ev.attendance = "in_person"

    locations = obj.get("location") or []
    locations = locations if isinstance(locations, list) else [locations]
    for loc in locations:
        if isinstance(loc, str):
            ev.location_name = ev.location_name or clean(loc)
            continue
        if not isinstance(loc, dict):
            continue
        if "VirtualLocation" in _types(loc):
            ev.online = True
            continue
        ev.location_name = ev.location_name or clean(loc.get("name"))
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [clean(addr.get(k)) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
            ev.address = ", ".join(p for p in parts if p)
            ev.locality = clean(addr.get("addressLocality"))
            ev.region = _region(clean(addr.get("addressRegion")) or ev.address)
            ev.country = clean(addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str)
                               else _name(addr.get("addressCountry")))
        elif isinstance(addr, str):
            ev.address = clean(addr)
    if not ev.region:
        ev.region = _region(" ".join([ev.location_name, ev.address]))
    if ev.online is None and ev.attendance:
        ev.online = ev.attendance in ("online", "hybrid")

    ev.host = _name(obj.get("organizer"))
    offers = obj.get("offers") or []
    offers = offers if isinstance(offers, list) else [offers]
    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        for key in ("price", "lowPrice", "highPrice"):
            try:
                if offer.get(key) not in (None, ""):
                    prices.append(float(str(offer[key]).replace("$", "").replace(",", "")))
            except ValueError:
                pass
    if prices:
        lo, hi = min(prices), max(prices)
        ev.free = hi == 0
        if hi == 0:
            ev.cost = "Free"
        elif lo == 0:
            ev.cost = f"Free and paid tickets (up to ${hi:,.0f})"
        else:
            ev.cost = f"${lo:,.0f}" if lo == hi else f"${lo:,.0f} to ${hi:,.0f}"
    if obj.get("isAccessibleForFree") in (True, "true", "True"):
        ev.free, ev.cost = True, ev.cost or "Free"

    ev.images = _images(obj.get("image"))
    status = str(obj.get("eventStatus", ""))
    for key, value in (("Cancelled", "cancelled"), ("Postponed", "postponed"), ("Rescheduled", "rescheduled"),
                       ("MovedOnline", "moved_online")):
        if key in status:
            ev.status = value
    keywords = obj.get("keywords") or []
    if isinstance(keywords, str):
        keywords = keywords.split(",")
    ev.tags = [clean(k) for k in keywords if isinstance(k, str) and k.strip()]
    return ev


def meta(markup: str) -> dict:
    """Open Graph / Twitter tags, <title> and the canonical link."""
    soup = BeautifulSoup(markup, "lxml")
    out = {}
    for tag in soup.find_all("meta"):
        key = tag.get("property") or tag.get("name")
        if key and tag.get("content") and key.lower() not in out:
            out[key.lower()] = clean(tag["content"])
    if soup.title and soup.title.string:
        out["title"] = clean(soup.title.string)
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        out["canonical"] = link["href"]
    return out


def links(markup: str, base: str, pattern: str | None = None) -> list[str]:
    """Absolute links on a page, in page order, without duplicates; optionally only those matching pattern."""
    soup = BeautifulSoup(markup, "lxml")
    rx = re.compile(pattern) if pattern else None
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"].strip()).split("#")[0]
        if not href.startswith("http") or href in seen:
            continue
        if rx and not rx.search(href):
            continue
        seen.add(href)
        out.append(href)
    return out


def links_in_text(markup: str, pattern: str) -> list[str]:
    """Links matching pattern anywhere in the page source, including inside embedded JSON (Meetup keeps its
    event links in page data rather than in <a href>)."""
    rx = re.compile(pattern)
    source = markup.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    seen, out = set(), []
    for m in re.finditer(r"https?://[^\s\"'<>\\]+", source):
        url = m.group(0).rstrip(".,;)")
        if url not in seen and rx.search(url):
            seen.add(url)
            out.append(url)
    return out


def registration_links(markup: str, base: str) -> list[str]:
    """Links to ticketing platforms that publish structured event data."""
    out = []
    for href in links(markup, base):
        host = re.sub(r"^www\.", "", href.split("/")[2].lower())
        if any(host == h or host.endswith("." + h) for h in STRUCTURED_HOSTS):
            out.append(href)
    return out


def page_images(markup: str, base: str, must_contain: str) -> list[str]:
    soup = BeautifulSoup(markup, "lxml")
    out = []
    for img in soup.find_all("img", src=True):
        src = urljoin(base, img["src"])
        if must_contain in src and src not in out:
            out.append(src)
    return out
