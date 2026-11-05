"""AISA branch event pages (iMIS, plain HTML with labelled fields)."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ..fetch import Blocked, FetchError
from ..model import RawEvent
from ..text import clean, html_to_text
from .base import Context, apply_defaults

_WHEN = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*([AP]M)(?:\s*-\s*(?:(\d{1,2})/(\d{1,2})/(\d{4})\s+)?"
    r"(\d{1,2}):(\d{2})\s*([AP]M))?", re.I)
_ZONES = {
    "eastern": "Australia/Sydney", "aedt": "Australia/Sydney", "aest": "Australia/Sydney",
    "tasmania": "Australia/Hobart", "central": "Australia/Adelaide", "acdt": "Australia/Adelaide",
    "acst": "Australia/Adelaide", "w. australia": "Australia/Perth", "western": "Australia/Perth",
    "awst": "Australia/Perth",
}


def _clock(h: str, m: str, ampm: str) -> tuple[int, int]:
    hour = int(h) % 12 + (12 if ampm.upper() == "PM" else 0)
    return hour, int(m)


def _after(lines: list[str], label: str, stop: tuple[str, ...] = ()) -> list[str]:
    """Lines following a label line ('When', 'Where', 'Register:') up to the next label."""
    if label not in lines:
        return []
    out = []
    for line in lines[lines.index(label) + 1:]:
        if line in stop or line.endswith(":") and len(line) < 25:
            break
        out.append(line)
    return out


def parse_event_page(markup: str, url: str, source: str, tz: ZoneInfo, heading: str = "") -> RawEvent | None:
    lines = html_to_text(markup).splitlines()
    text = "\n".join(lines)
    m = _WHEN.search(text)
    if not m:
        return None
    zone_line = (_after(lines, "When", ("Where",)) + [""])[1].lower() if "When" in lines else ""
    zone = next((z for key, z in _ZONES.items() if key in zone_line), "Australia/Sydney")
    local = ZoneInfo(zone)
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    start = datetime(y, mo, d, *_clock(m.group(4), m.group(5), m.group(6)), tzinfo=local).astimezone(tz)
    end = None
    if m.group(10):
        ed = (int(m.group(7)), int(m.group(8)), int(m.group(9))) if m.group(7) else (d, mo, y)
        end = datetime(ed[2], ed[1], ed[0], *_clock(m.group(10), m.group(11), m.group(12)),
                       tzinfo=local).astimezone(tz)

    title = ""
    for label in ("Webinar Title:", "Event Title:", "Title:"):
        if label in lines:
            title = clean(lines[lines.index(label) + 1])
            break
    heading = heading or next((l for l in lines if l.startswith("AISA ") and "|" in l), "")
    kind = clean(heading.split("|")[0]) if heading else "AISA"
    if not title:
        quoted = re.search(r"['‘\"“]([^'’\"”]{8,140})['’\"”]", text)
        title = quoted.group(1) if quoted else clean(heading.split("|")[0])
    if kind and not title.lower().startswith(kind.lower()):
        title = f"{kind}: {title}"

    where = [l for l in _after(lines, "Where", ("Back to Top",)) if l.upper() != "AUSTRALIA"]
    online = bool(re.search(r"\b(online|webinar|zoom|teams)\b", " ".join(where) + " " + heading, re.I))
    register = " ".join(_after(lines, "Register:"))
    body = []
    start_at = lines.index(title.split(": ", 1)[-1]) + 1 if title.split(": ", 1)[-1] in lines else 0
    for line in lines[start_at:]:
        if line in ("Speakers:", "Speaker:", "Register:", "Date:", "When"):
            break
        body.append(line)
    branch = re.search(r"\|\s*([A-Za-z ]+Branch)\s*\|", heading)
    ev = RawEvent(
        source=source, url=url, title=clean(title), start=start, end=end, description=clean(" ".join(body)),
        online=online, attendance="online" if online else "in_person",
        location_name="" if online else ", ".join(where), region="" if online else "TAS",
        host=f"AISA {branch.group(1)}" if branch else "AISA",
    )
    low = register.lower()
    if "free" in low:
        ev.free = True
        ev.cost = "Free for AISA members" if "member" in low else "Free"
    elif register:
        ev.cost = clean(register)[:120]
    if "only available to aisa members" in low or "members only" in low:
        ev.extra["members_only"] = True
    return ev


def collect(cfg: dict, ctx: Context) -> list[RawEvent]:
    found: dict[str, str] = {}  # event url -> heading
    for branch, listing_url in (cfg.get("branches") or {}).items():
        try:
            page = ctx.fetcher.get(listing_url)
        except (Blocked, FetchError) as exc:
            ctx.note(f"AISA {branch}: {exc}")
            continue
        soup = BeautifulSoup(page.text, "lxml")
        for a in soup.select("h2 a[href*='EventKey=']"):
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.aisa.org.au" + href
            found.setdefault(href, clean(a.get_text()))
    events = []
    for url, heading in found.items():
        if ctx.skip_url(url):
            continue
        try:
            page = ctx.fetcher.get(url)
        except (Blocked, FetchError) as exc:
            ctx.note(f"{url}: {exc}")
            continue
        ev = parse_event_page(page.text, url, cfg["id"], ctx.tz, heading)
        if ev:
            events.append(apply_defaults(ev, cfg))
        else:
            ctx.note(f"{url}: no date found on the page")
    return events
