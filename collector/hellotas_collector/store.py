"""The site's event files, the collector's ledger and ignore list, and writing new entries.

Duplicates are caught three ways:
  1. the same link (ignoring www, tracking parameters and case) as any upcoming or archived event, including the
     links listed under `references` in archived events;
  2. the same day and a similar title (the same event published on two platforms, e.g. GDG Hobart on Bevy and
     Meetup);
  3. the ledger: every event the collector ever proposed. If a proposed event's file is gone, someone removed it
     on purpose, and the collector leaves it alone.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Q

from .extract import parse_when
from .model import LANGS, RawEvent
from .text import title_similarity, url_key


def yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)  # matches the hand-written files exactly
    return y


@dataclass
class Entry:
    path: Path
    kind: str  # "happening" (upcoming) or "archive" (past events)
    data: dict
    keys: set[str] = field(default_factory=set)
    title: str = ""
    start: datetime | None = None

    @property
    def slug(self) -> str:
        return self.path.stem

    @property
    def managed(self) -> bool:
        """Written by the collector (it adds `source:`), so it may correct the dates."""
        return "source" in self.data


def _text(v) -> str:
    if isinstance(v, dict):
        return str(v.get("en") or next(iter(v.values()), ""))
    return str(v or "")


class Site:
    def __init__(self, root: Path, tz: ZoneInfo):
        self.root = root
        self.tz = tz
        self.happening_dir = root / "data" / "happening"
        self.archive_dir = root / "data" / "events"
        self.static_dir = root / "static"
        self.entries: list[Entry] = []
        self._load()

    def _load(self) -> None:
        y = yaml()
        files = [(p, "happening") for p in sorted(self.happening_dir.glob("*.yaml"))]
        files += [(p, "archive") for p in sorted(self.archive_dir.glob("*/*.yaml"))]
        for path, kind in files:
            try:
                data = y.load(path.read_text(encoding="utf-8")) or {}
            except Exception:  # a broken file shouldn't stop the run; Hugo will complain about it anyway
                continue
            entry = Entry(path=path, kind=kind, data=data, title=_text(data.get("title")))
            entry.start, _ = parse_when(data.get("start"), self.tz)
            for url in [data.get("url")] + [r.get("url") for r in data.get("references") or [] if isinstance(r, dict)]:
                if url:
                    entry.keys.add(url_key(str(url)))
            self.entries.append(entry)

    @property
    def slugs(self) -> set[str]:
        return {e.slug for e in self.entries}

    def by_key(self, key: str) -> Entry | None:
        return next((e for e in self.entries if key in e.keys), None)

    def similar(self, ev: RawEvent) -> Entry | None:
        """An existing entry on (about) the same date with a similar title."""
        if not ev.start:
            return None
        best, best_score = None, 0.0
        for e in self.entries:
            if not e.start:
                continue
            days = abs((e.start.date() - ev.start.date()).days)
            if days > 2:
                continue
            score = title_similarity(e.title, ev.title)
            needed = 0.6 if days == 0 else 0.82
            if score >= needed and score > best_score:
                best, best_score = e, score
        return best

    def match(self, ev: RawEvent) -> tuple[Entry | None, str]:
        keys = {url_key(ev.url)}
        if ev.extra.get("listing_page"):
            keys.add(url_key(ev.extra["listing_page"]))
        for key in keys:
            entry = self.by_key(key)
            if entry:
                return entry, "same link"
        entry = self.similar(ev)
        return (entry, "same date, similar title") if entry else (None, "")

    def free_slug(self, wanted: str, start: datetime | None) -> str:
        slug = re.sub(r"[^a-z0-9-]+", "-", wanted.lower()).strip("-")[:60].strip("-") or "event"
        taken = self.slugs | {p.name for p in (self.static_dir / "images" / "happening").glob("*")}
        if slug not in taken:
            return slug
        if start and str(start.year) not in slug:
            candidate = f"{slug}-{start.year}"
            if candidate not in taken:
                return candidate
        n = 2
        while f"{slug}-{n}" in taken:
            n += 1
        return f"{slug}-{n}"


class Ledger:
    """collector/ledger.yaml: link key -> what was proposed and when."""

    HEADER = (
        "# Every event the collector has proposed, so it never proposes one twice.\n"
        "# If you delete an event's file (or close the collector's pull request), its line stays here and the\n"
        "# collector won't add it again. Delete the line to let it come back.\n"
    )

    def __init__(self, path: Path):
        self.path = path
        self.events: dict[str, dict] = {}
        if path.exists():
            data = yaml().load(path.read_text(encoding="utf-8")) or {}
            self.events = dict(data.get("events") or {})

    def __contains__(self, key: str) -> bool:
        return key in self.events

    def add(self, key: str, record: dict) -> None:
        self.events[key] = record

    def save(self) -> None:
        doc = CommentedMap()
        events = CommentedMap()
        for key in sorted(self.events):
            rec = CommentedMap()
            for k, v in self.events[key].items():
                rec[k] = Q(str(v))
            rec.fa.set_flow_style()
            events[Q(key)] = rec
        doc["events"] = events
        buf = io.StringIO()
        yaml().dump(doc, buf)
        self.path.write_text(self.HEADER + buf.getvalue(), encoding="utf-8")


class IgnoreList:
    """collector/ignore.yaml: links (or regular expressions) the collector must never add."""

    def __init__(self, path: Path):
        self.exact: set[str] = set()
        self.patterns: list[re.Pattern] = []
        if path.exists():
            data = yaml().load(path.read_text(encoding="utf-8")) or {}
            for item in data.get("links") or []:
                self.exact.add(url_key(str(item)))
            for item in data.get("patterns") or []:
                self.patterns.append(re.compile(str(item), re.I))

    def __contains__(self, url: str) -> bool:
        return url_key(url) in self.exact or any(p.search(url) for p in self.patterns)


def iso(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).isoformat(timespec="seconds")


def _i18n(value: dict) -> CommentedMap:
    m = CommentedMap()
    for lang in LANGS:
        if value.get(lang):
            m[lang] = Q(value[lang])
    return m


def build_entry(fields: dict, ev: RawEvent, tz: ZoneInfo, image: str, added: str) -> CommentedMap:
    """A new data/happening entry, in the same field order and quoting as the hand-written files."""
    doc = CommentedMap()
    doc["title"] = _i18n(fields["title"])
    start = ev.start
    end = ev.end if ev.end and ev.end > start else (start + timedelta(hours=1) if not ev.all_day else
                                                    start.replace(hour=23, minute=59))
    doc["start"] = Q(iso(start, tz))
    doc["end"] = Q(iso(end, tz))
    if ev.all_day:
        doc["all_day"] = True
    doc["type"] = Q(fields["type"])
    doc["format"] = Q(fields["format"])
    topics = CommentedSeq(fields["topics"])
    topics.fa.set_flow_style()
    doc["topics"] = topics
    if fields.get("host"):
        doc["host"] = Q(fields["host"])
    if fields.get("location") and fields["format"] != "online":
        doc["location"] = _i18n(fields["location"])
    doc["cost"] = _i18n(fields["cost"])
    doc["summary"] = _i18n(fields["summary"])
    if image:
        doc["image"] = Q(image)
    doc["url"] = Q(ev.url)
    doc["source"] = Q(ev.source)
    doc["added"] = Q(added)
    return doc


def dump(doc: CommentedMap, header: str = "") -> str:
    buf = io.StringIO()
    yaml().dump(doc, buf)
    return header + buf.getvalue()


def update_dates(entry: Entry, ev: RawEvent, tz: ZoneInfo) -> list[str]:
    """For collector-made entries: follow the organiser's new date or time. Returns what changed."""
    changes = []
    if not entry.managed or not ev.start:
        return changes
    for key, new in (("start", ev.start), ("end", ev.end)):
        if new is None:
            continue
        before = str(entry.data.get(key) or "none")
        old, _ = parse_when(entry.data.get(key), tz)
        if old is None or abs((old - new).total_seconds()) >= 60:
            entry.data[key] = Q(iso(new, tz))
            changes.append(f"{key}: {before} → {iso(new, tz)}")
    if changes:
        buf = io.StringIO()
        yaml().dump(entry.data, buf)  # round-trip: comments, quoting and order are kept
        entry.path.write_text(buf.getvalue(), encoding="utf-8")
    return changes
