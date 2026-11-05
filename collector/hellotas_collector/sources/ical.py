"""An iCalendar (.ics) feed."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from icalendar import Calendar

from ..model import RawEvent
from ..text import clean, clean_title
from .base import Context, apply_defaults


def _when(value, tz) -> tuple[datetime | None, bool]:
    if value is None:
        return None, False
    v = value.dt
    if isinstance(v, datetime):
        return (v.replace(tzinfo=tz) if v.tzinfo is None else v).astimezone(tz), False
    if isinstance(v, date):
        return datetime.combine(v, time(0, 0), tz), True
    return None, False


def parse_calendar(data: bytes | str, source: str, tz) -> list[RawEvent]:
    cal = Calendar.from_ical(data)
    events = []
    for comp in cal.walk("VEVENT"):
        start, all_day = _when(comp.get("DTSTART"), tz)
        end, _ = _when(comp.get("DTEND"), tz)
        if all_day and start is not None:
            # An all-day DTEND is exclusive (the day after the last day). The site's convention is the last
            # day at 23:59, as in data/happening/telstra-iot-fest-2026.yaml.
            last_day = (end.date() - timedelta(days=1)) if end is not None and end.date() > start.date() \
                else start.date()
            end = datetime.combine(last_day, time(23, 59), tz)
        url = clean(str(comp.get("URL") or ""))
        status = str(comp.get("STATUS") or "").upper()
        ev = RawEvent(
            source=source, url=url, title=clean_title(str(comp.get("SUMMARY") or "")), start=start, end=end,
            all_day=all_day, description=clean(str(comp.get("DESCRIPTION") or "")),
            location_name=clean(str(comp.get("LOCATION") or "")),
            status="cancelled" if status == "CANCELLED" else "scheduled",
        )
        ev.extra["uid"] = str(comp.get("UID") or "")
        events.append(ev)
    return events


def collect(cfg: dict, ctx: Context) -> list[RawEvent]:
    page = ctx.fetcher.get(cfg["url"], accept="text/calendar")
    events = []
    for ev in parse_calendar(page.body, cfg["id"], ctx.tz):
        if not ev.url:
            continue  # nothing to link to
        events.append(apply_defaults(ev, cfg))
    return events
