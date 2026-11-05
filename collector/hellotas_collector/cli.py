"""Command line: `hellotas-collect <command>` (or `python -m hellotas_collector <command>`)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import issue_form, notify
from .config import find_root, load
from .fetch import Blocked, Fetcher, FetchError
from .pipeline import Collector, RunResult
from .report import markdown


def _write_outputs(result: RunResult, report: str, args) -> None:
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"added={len(result.added)}\n")
            fh.write(f"updated={len(result.updated)}\n")
            fh.write(f"changed={'true' if result.changed else 'false'}\n")
            fh.write(f"slugs={' '.join(p.slug for p in result.added)}\n")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "added": [{"slug": p.slug, "title": p.fields["title"]["en"], "url": p.raw.url, "file": p.file_path,
                       "start": p.raw.start.isoformat() if p.raw.start else None, "score": p.judgement.score,
                       "reason": p.judgement.reason} for p in result.added],
            "updated": [{"file": str(u.entry.path), "changes": u.changes} for u in result.updated],
            "errors": result.errors,
        }, ensure_ascii=False, indent=2), encoding="utf-8")


def _collector(args, public_only: bool = False) -> Collector:
    root = Path(args.root).resolve() if args.root else find_root()
    config = load(root / "collector" / "sources.yaml")
    now = datetime.fromisoformat(args.now).astimezone(ZoneInfo(config.timezone)) if args.now else None
    use_ai = False if args.no_ai else None
    return Collector(root, config, now=now, use_ai=use_ai, dry_run=args.dry_run, images=not args.no_images,
                     public_only=public_only)


def cmd_run(args) -> int:
    collector = _collector(args)
    only = [s.strip() for s in args.sources.split(",")] if args.sources else None
    result = collector.run(only)
    report = markdown(result)
    print(report)
    _write_outputs(result, report, args)
    return 0


def cmd_suggest(args) -> int:
    url, text, note = args.url, "", args.note or ""
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    if args.from_issue:
        # The issue body comes through an environment variable, never through the command line or a shell
        form = issue_form.suggestion(os.environ.get("ISSUE_BODY", ""))
        url, text, note = form["url"], form["details"], form["note"]
    if not url and text:
        url = issue_form.first_link(text)
    if not url:
        report = ("## Event suggestion\n\nI couldn't find a link in the suggestion. Edit the issue and put the "
                  "event's web address in the *Event link* field.\n")
        print(report)
        _write_outputs(RunResult(errors={"suggestion": "no link"}), report, args)
        return 0
    collector = _collector(args, public_only=True)
    result = collector.suggest(url, pasted_text=text, note=note)
    report = markdown(result, heading="Event suggestion")
    print(report)
    _write_outputs(result, report, args)
    return 0


def cmd_sources(args) -> int:
    root = Path(args.root).resolve() if args.root else find_root()
    config = load(root / "collector" / "sources.yaml")
    fetcher = Fetcher(config.user_agent, delay=config.delay_seconds)
    for s in config.sources:
        state = "on " if s.get("enabled", True) else "off"
        line = f"[{state}] {s['id']:<24} {s.get('kind', ''):<7} {s.get('name', '')}"
        if args.check:
            url = s.get("listing") or s.get("url") or next(iter((s.get("branches") or {}).values()), "")
            try:
                page = fetcher.get(url)
                line += f"  -> OK ({len(page.body):,} bytes)"
            except Blocked as exc:
                line += f"  -> BLOCKED: {exc}"
            except FetchError as exc:
                line += f"  -> ERROR: {exc}"
        print(line)
    return 0


def cmd_discord(args) -> int:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    new = notify.load(args.new)
    if new is None:
        print(f"No events file at {args.new}; nothing to announce.")
        return 0
    old = notify.load(args.old)
    if old is None:
        print("No previous events file (first deploy?); not announcing everything at once.")
        return 0
    fresh = notify.new_events(old, new)
    print(f"{len(fresh)} new event(s): " + ", ".join(e["id"] for e in fresh))
    if fresh and webhook:
        print(f"Posted {notify.post(webhook, fresh)} to Discord.")
    elif fresh:
        print("DISCORD_WEBHOOK_URL isn't set; not posting.")
    return 0


def cmd_check_site(args) -> int:
    """Validate the feeds in a built site (hugo -d <folder>): every .ics parses, uses CRLF and folds at 75 octets;
    every happening/index.json lists events with the fields the API and the Discord announcer rely on."""
    from icalendar import Calendar
    public = Path(args.public)
    problems = []
    calendars = sorted(public.rglob("*.ics"))
    for path in calendars:
        raw = path.read_bytes()
        try:
            raw.decode("utf-8")
            lines = raw.split(b"\r\n")
            if lines[-1] != b"" or any(b"\n" in line for line in lines):
                problems.append(f"{path}: lines must end with CRLF")
            if max(len(line) for line in lines) > 75:
                problems.append(f"{path}: a line is longer than 75 octets")
            Calendar.from_ical(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            problems.append(f"{path}: {exc}")
    feeds = sorted(public.rglob("happening/index.json"))
    for path in feeds:
        data = json.loads(path.read_text(encoding="utf-8"))
        for event in data.get("events", []):
            missing = [k for k in ("id", "title", "start", "end", "format", "page") if not event.get(k)]
            if missing:
                problems.append(f"{path}: {event.get('id')} lacks {', '.join(missing)}")
    print(f"{len(calendars)} calendar file(s), {len(feeds)} JSON feed(s) checked.")
    for p in problems:
        print("PROBLEM:", p)
    if not calendars or not feeds:
        print("PROBLEM: no feeds found; is this the built site?")
        return 1
    return 1 if problems else 0


def cmd_ledger_merge(args) -> int:
    """Add another ledger's entries to ours (used when a collector pull request is closed without merging, so its
    events count as rejected)."""
    from .store import Ledger
    root = Path(args.root).resolve() if args.root else find_root()
    ours = Ledger(root / "collector" / "ledger.yaml")
    theirs = Ledger(Path(args.other))
    added = 0
    for key, record in theirs.events.items():
        if key not in ours:
            ours.add(key, {**record, "rejected": datetime.now(ZoneInfo("Australia/Hobart")).date().isoformat()})
            added += 1
    if added:
        ours.save()
    print(f"{added} rejected event(s) remembered.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hellotas-collect", description=__doc__)
    parser.add_argument("--root", help="site root (default: the folder with hugo.toml above here)")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--dry-run", action="store_true", help="read and judge, but write nothing")
        p.add_argument("--no-ai", action="store_true", help="use the keyword rules even if an API key is set")
        p.add_argument("--no-images", action="store_true", help="don't download cover pictures")
        p.add_argument("--report", help="also write the Markdown report to this file")
        p.add_argument("--json", help="also write a JSON summary to this file")
        p.add_argument("--now", help=argparse.SUPPRESS)  # pretend it's this time (tests)

    p = sub.add_parser("run", help="read every enabled source and add new events")
    p.add_argument("--sources", help="comma-separated source ids (default: all enabled)")
    common(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("suggest", help="add the event at one link (what the suggestion form runs)")
    p.add_argument("url", nargs="?", default="")
    p.add_argument("--text-file", help="pasted event details (for LinkedIn and other pages that can't be fetched)")
    p.add_argument("--note", help="the suggester's note for reviewers")
    p.add_argument("--from-issue", action="store_true", help="read the link and details from $ISSUE_BODY")
    common(p)
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("sources", help="list sources (--check: see whether each can be reached)")
    p.add_argument("--check", action="store_true")
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("discord", help="post events that are new since the last deploy to Discord")
    p.add_argument("--old", required=True, help="events.json before the deploy")
    p.add_argument("--new", required=True, help="events.json after the deploy")
    p.set_defaults(func=cmd_discord)

    p = sub.add_parser("check-site", help="validate the calendar and JSON feeds of a built site")
    p.add_argument("public", help="the folder hugo built into (usually public/)")
    p.set_defaults(func=cmd_check_site)

    p = sub.add_parser("ledger-merge", help="remember the events of a closed, unmerged collector pull request")
    p.add_argument("other", help="the ledger.yaml from that pull request's branch")
    p.set_defaults(func=cmd_ledger_merge)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
