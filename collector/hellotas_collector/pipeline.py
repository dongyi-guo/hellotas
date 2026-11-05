"""One collector run: read the sources, weed out what doesn't belong, write the rest."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import rules
from .ai import AIUnavailable, Editor, credentials_present
from .config import Config
from .fetch import Blocked, Fetcher, FetchError
from .images import save_cover
from .model import LANGS, Judgement, Proposal, RawEvent, Skip
from .sources import KINDS, Context
from .sources.page import resolve_url
from .store import Entry, IgnoreList, Ledger, Site, build_entry, dump, iso, update_dates
from .text import slugify, url_key


@dataclass
class Update:
    entry: Entry
    changes: list[str]
    raw: RawEvent


@dataclass
class RunResult:
    added: list[Proposal] = field(default_factory=list)
    updated: list[Update] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    found: dict[str, int] = field(default_factory=dict)  # source id -> events read
    errors: dict[str, str] = field(default_factory=dict)  # source id -> why it couldn't be read
    notes: dict[str, list[str]] = field(default_factory=dict)
    ai: dict = field(default_factory=dict)
    dry_run: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated)


def style_examples(site: Site, limit: int) -> list[dict]:
    """Hand-written entries (with all three languages) the AI copies the tone and translation choices from."""
    out = []
    for e in sorted((e for e in site.entries if e.kind == "happening" and not e.managed), key=lambda e: e.slug):
        d = e.data
        if not all(isinstance(d.get(k), dict) and d[k].get("zh") and d[k].get("ne") for k in ("title", "summary")):
            continue
        out.append({k: (dict(d[k]) if isinstance(d.get(k), dict) else d.get(k)) for k in (
            "title", "type", "format", "topics", "host", "location", "cost", "summary") if d.get(k) is not None})
        if len(out) >= limit:
            break
    for ex in out:
        if "topics" in ex:
            ex["topics"] = list(ex["topics"])
    return out


class Collector:
    def __init__(self, root: Path, config: Config, now: datetime | None = None, use_ai: bool | None = None,
                 dry_run: bool = False, images: bool = True, client=None, fetcher: Fetcher | None = None,
                 public_only: bool = False, log=print):
        self.root = root
        self.config = config
        self.tz = ZoneInfo(config.timezone)
        self.now = now or datetime.now(self.tz)
        self.dry_run = dry_run
        self.images = images
        self.log = log
        self.site = Site(root, self.tz)
        self.ledger = Ledger(root / "collector" / "ledger.yaml")
        self.ignore = IgnoreList(root / "collector" / "ignore.yaml")
        self.fetcher = fetcher or Fetcher(config.user_agent, delay=config.delay_seconds, public_only=public_only)
        # None means "decide from the settings": on only if sources.yaml switches it on and a key is set
        use_ai = (config.ai_enabled and credentials_present()) if use_ai is None else use_ai
        self.editor: Editor | None = None
        if use_ai:
            ai = config.ai
            self.editor = Editor(
                model=ai.get("model", "claude-opus-5-5"), triage_effort=ai.get("triage_effort", "low"),
                write_effort=ai.get("write_effort", "medium"),
                examples=style_examples(self.site, int(ai.get("style_examples", 6))),
                cache_path=root / "collector" / ".cache" / "ai-cache.json", client=client, tz=self.tz, now=self.now)
        self.result = RunResult(dry_run=dry_run)

    # -- helpers ----------------------------------------------------------------------------------------------
    def skip_url(self, url: str) -> bool:
        """Links not worth opening: archived events, ignored links, proposals someone removed."""
        if url in self.ignore:
            return True
        key = url_key(url)
        entry = self.site.by_key(key)
        if entry is not None:
            return entry.kind == "archive"
        return key in self.ledger

    def context(self) -> Context:
        return Context(fetcher=self.fetcher, tz=self.tz, now=self.now, skip_url=self.skip_url,
                       read_page=self._read_page if self.editor else None)

    def _read_page(self, text: str, url: str, source: str) -> list[RawEvent]:
        try:
            return self.editor.read_page(text, url, source)
        except AIUnavailable as exc:
            self.result.notes.setdefault(source, []).append(f"AI couldn't read {url}: {exc}")
            return []

    def _skip(self, raw: RawEvent, why: str, detail: str = "") -> None:
        self.result.skipped.append(Skip(raw, why, detail))

    # -- judging and writing ----------------------------------------------------------------------------------
    def judge(self, raw: RawEvent, suggested: bool) -> Judgement:
        by_rules = rules.judge(raw)
        if self.editor is None:
            return by_rules
        if not suggested and by_rules.score < 25:
            return by_rules  # clearly not for us; no need to pay for a second opinion
        try:
            return self.editor.triage(raw)
        except AIUnavailable as exc:
            by_rules.reason += f" (AI unavailable: {exc})"
            return by_rules

    def write_fields(self, raw: RawEvent) -> tuple[dict, str]:
        if self.editor is not None:
            try:
                return self.editor.write(raw), "ai"
            except AIUnavailable as exc:
                self.result.notes.setdefault(raw.source, []).append(f"{raw.title}: written by rules ({exc})")
        return rules.write(raw), "rules"

    def consider(self, raw: RawEvent, suggested: bool = False) -> Proposal | None:
        if not raw.title or not raw.start:
            self._skip(raw, "no date", "the page doesn't say when it is")
            return None
        if (raw.end or raw.start) < self.now:
            self._skip(raw, "over")
            return None
        if raw.start > self.now + timedelta(days=self.config.horizon_days):
            self._skip(raw, "too far ahead", raw.start.date().isoformat())
            return None
        if raw.url in self.ignore:
            self._skip(raw, "on the ignore list")
            return None
        entry, how = self.site.match(raw)
        if entry is not None:
            if entry.kind == "happening" and entry.managed and not self.dry_run:
                changes = update_dates(entry, raw, self.tz)
                if changes:
                    self.result.updated.append(Update(entry, changes, raw))
            self._skip(raw, "already listed", f"{entry.kind}/{entry.slug} ({how})")
            return None
        key = url_key(raw.url)
        if key in self.ledger:
            self._skip(raw, "removed before", "proposed earlier and taken out; delete its ledger line to allow it")
            return None
        if raw.status == "cancelled":
            self._skip(raw, "cancelled")
            return None

        judgement = self.judge(raw, suggested)
        if suggested:
            judgement.by = "person" if judgement.by == "rules" else judgement.by
        elif not judgement.relevant or judgement.score < self.config.min_relevance:
            self._skip(raw, "not relevant", f"{judgement.score}/100 by {judgement.by}: {judgement.reason}")
            return None

        fields, written_by = self.write_fields(raw)
        if not fields.get("host"):
            fields["host"] = raw.host
        wanted = fields.get("slug") or slugify(_slug_basis(raw, fields))
        slug = self.site.free_slug(wanted, raw.start)
        image, image_note, borrowed = "", "", ""
        if self.images and not self.dry_run:
            if raw.images:
                image, image_note = save_cover(self.fetcher, raw.images, self.site.static_dir, slug)
            if not image:  # every event on the site has a picture
                image, borrowed = self.borrow_picture(raw, fields, slug)
                self.result.notes.setdefault(raw.source, []).append(
                    f"{slug}: the organiser's picture couldn't be downloaded"
                    + (f" ({image_note})" if image_note else "") + f"; using {borrowed} for now")
        doc = build_entry(fields, raw, self.tz, image, self.now.date().isoformat())
        path = self.site.happening_dir / f"{slug}.yaml"
        source_name = (self.config.source(raw.source) or {}).get("name", raw.source)
        header = (f"# Added by the event collector from {source_name} on {self.now.date().isoformat()}.\n"
                  "# Edit anything. The collector only ever changes start and end, when the organiser does.\n")
        if not self.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dump(doc, header), encoding="utf-8")
        record = {"slug": slug, "title": fields["title"]["en"], "start": iso(raw.start, self.tz)[:10],
                  "source": raw.source, "proposed": self.now.date().isoformat()}
        self.ledger.add(key, record)
        if raw.extra.get("listing_page"):
            self.ledger.add(url_key(raw.extra["listing_page"]), record)
        new_entry = Entry(path=path, kind="happening", data=doc, keys={key}, title=fields["title"]["en"],
                          start=raw.start)
        self.site.entries.append(new_entry)  # so a second source's copy of this event is caught as a duplicate
        proposal = Proposal(raw=raw, slug=slug, fields=fields, judgement=judgement, written_by=written_by,
                            image_path=image, image_borrowed=borrowed, file_path=str(path.relative_to(self.root)))
        self.result.added.append(proposal)
        return proposal

    def borrow_picture(self, raw: RawEvent, fields: dict, slug: str) -> tuple[str, str]:
        """When the organiser's own picture can't be downloaded: a copy of the most recent picture used for the same
        organiser (same source or host), or else the default_image in sources.yaml. Returns (site path, where from)."""
        static = self.site.static_dir
        host = (fields.get("host") or raw.host or "").strip().lower()
        candidates = []
        for e in self.site.entries:
            picture = e.data.get("image")
            if not picture or not (static / str(picture).lstrip("/")).is_file():
                continue
            same_source = e.data.get("source") == raw.source and raw.source not in ("suggestion",)
            same_host = host and str(e.data.get("host") or "").strip().lower() == host
            if same_source or same_host:
                candidates.append((e.start.isoformat() if e.start else "", str(picture), e.slug))
        if candidates:
            _, picture, origin = max(candidates)
            source_file, label = static / picture.lstrip("/"), f"the picture from {origin}"
        elif self.config.default_image and (static / self.config.default_image.lstrip("/")).is_file():
            source_file, label = static / self.config.default_image.lstrip("/"), "the site's default picture"
        else:
            return "", "nothing (no default_image found)"
        target = static / "images" / "happening" / slug / f"{slug}-1{source_file.suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target)
        return "/" + str(target.relative_to(static)).replace("\\", "/"), label

    # -- runs -------------------------------------------------------------------------------------------------
    def run(self, only: list[str] | None = None) -> RunResult:
        ctx = self.context()
        for cfg in self.config.enabled_sources(only):
            collect = KINDS.get(cfg.get("kind"))
            if collect is None:
                self.result.errors[cfg["id"]] = f"unknown kind {cfg.get('kind')!r}"
                continue
            ctx.notes = []
            try:
                raws = collect(cfg, ctx)
            except Blocked as exc:
                self.result.errors[cfg["id"]] = f"blocked: {exc}"
                raws = []
            except FetchError as exc:
                self.result.errors[cfg["id"]] = str(exc)
                raws = []
            except Exception as exc:  # one broken source must not stop the others
                self.result.errors[cfg["id"]] = f"{exc.__class__.__name__}: {exc}"
                raws = []
            self.result.found[cfg["id"]] = len(raws)
            if ctx.notes:
                self.result.notes.setdefault(cfg["id"], []).extend(ctx.notes)
            for raw in sorted(raws, key=lambda r: r.start or self.now):
                self.consider(raw)
        return self.finish()

    def suggest(self, url: str, pasted_text: str = "", note: str = "") -> RunResult:
        """A link someone suggested (GitHub issue form or the website)."""
        ctx = self.context()
        try:
            raws = resolve_url(url, ctx, pasted_text=pasted_text)
        except (Blocked, FetchError) as exc:
            self.result.errors["suggestion"] = str(exc)
            raws = []
        if ctx.notes:
            self.result.notes["suggestion"] = ctx.notes
        self.result.found["suggestion"] = len(raws)
        for raw in raws:
            raw.extra.setdefault("trust", "high")
            if note:
                raw.extra["suggester_note"] = note[:500]
            self.consider(raw, suggested=True)
        if not raws and "suggestion" not in self.result.errors:
            self.result.errors["suggestion"] = ("No upcoming event with a date could be read from that link. "
                                                "Link the event's own page, or paste its details into the form.")
        return self.finish()

    def finish(self) -> RunResult:
        if not self.dry_run and self.result.added:
            self.ledger.save()
        if self.editor is not None:
            self.editor.save()
            self.result.ai = {"model": self.editor.model, "calls": self.editor.calls,
                              "cache_hits": self.editor.cache_hits, "input_tokens": self.editor.input_tokens,
                              "output_tokens": self.editor.output_tokens}
        return self.result


def _slug_basis(raw: RawEvent, fields: dict) -> str:
    title = fields["title"]["en"]
    host = (fields.get("host") or raw.host or "").split(" ")[0]
    if host and host.lower() not in title.lower():
        return f"{host} {title}"
    return title


__all__ = ["Collector", "RunResult", "LANGS"]
