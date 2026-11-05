"""A Markdown summary of a run, for pull request descriptions, issue replies and the Actions summary."""

from __future__ import annotations

from collections import Counter

from .pipeline import RunResult

# US dollars per million tokens (input, output), for the cost line only
PRICES = {
    "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0), "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50), "claude-fable-5-1": (10.0, 50.0),
}


def _when(raw) -> str:
    if not raw.start:
        return "date unknown"
    return raw.start.strftime("%a %-d %b %Y") + ("" if raw.all_day else raw.start.strftime(" · %-I:%M %p").lower())


def _md(s: str) -> str:
    """Text from event pages, made safe for a table cell and for GitHub: no @mentions, no table breaks."""
    return str(s).replace("|", "\\|").replace("\n", " ").replace("@", "@\u200b")


def markdown(result: RunResult, heading: str = "Event collector run") -> str:
    out = [f"## {heading}", ""]
    blocked = {k: v for k, v in result.errors.items()}
    out.append(
        f"**{len(result.added)} new**, {len(result.updated)} updated, {len(result.skipped)} skipped. "
        f"{len(result.found)} source(s) read" + (f", {len(blocked)} couldn't be read." if blocked else ".")
        + (" Dry run: nothing was written." if result.dry_run else ""))
    out.append("")

    if result.added:
        out += ["### New events", "", "| When (Hobart time) | Event | Host | Relevance | Text by | File |",
                "|---|---|---|---|---|---|"]
        for p in result.added:
            j = p.judgement
            score = f"{j.score} ({j.by})" if j.by != "person" else f"{j.score} (suggested)"
            out.append(f"| {_when(p.raw)} | [{_md(p.fields['title']['en'])}]({p.raw.url}) | {_md(p.fields.get('host', ''))} "
                       f"| {score} | {p.written_by} | `{p.file_path}` |")
        out += ["", "<details><summary>Why each was picked</summary>", ""]
        for p in result.added:
            note = p.raw.extra.get("suggester_note")
            out.append(f"- **{_md(p.fields['title']['en'])}**: {_md(p.judgement.reason)}"
                       + (f" Suggester's note: {_md(note)}" if note else "")
                       + (f" **Picture: {p.image_borrowed} for now; replace it with the event's own.**"
                          if p.image_borrowed else ""))
        out += ["", "</details>", ""]

    if result.updated:
        out += ["### Updated", ""]
        for u in result.updated:
            out.append(f"- `{u.entry.path.name}`: " + "; ".join(u.changes))
        out.append("")

    out += ["### Sources", "", "| Source | Events read | Status |", "|---|---|---|"]
    for source in sorted(set(result.found) | set(result.errors)):
        status = _md(result.errors.get(source, "ok"))
        out.append(f"| {source} | {result.found.get(source, 0)} | {status} |")
    out.append("")

    if result.skipped:
        counts = Counter(s.why for s in result.skipped)
        out += ["<details><summary>Skipped: " + ", ".join(f"{n} {why}" for why, n in counts.most_common())
                + "</summary>", ""]
        for s in sorted(result.skipped, key=lambda s: (s.why, s.raw.start.isoformat() if s.raw.start else "")):
            if s.why in ("over",):
                continue
            out.append(f"- {s.why}: [{_md(s.raw.title or s.raw.url)}]({s.raw.url}) ({_when(s.raw)})"
                       + (f", {_md(s.detail)}" if s.detail else ""))
        out += ["", "</details>", ""]

    notes = [(src, n) for src, items in result.notes.items() for n in items]
    if notes:
        out += ["<details><summary>Notes</summary>", ""] + [f"- {src}: {_md(n)}" for src, n in notes[:60]]
        out += ["", "</details>", ""]

    if result.ai:
        ai = result.ai
        price = PRICES.get(ai["model"])
        cost = ""
        if price:
            usd = ai["input_tokens"] / 1e6 * price[0] + ai["output_tokens"] / 1e6 * price[1]
            cost = f", about US${usd:.2f}"
        out.append(f"AI: {ai['model']}, {ai['calls']} call(s), {ai['cache_hits']} answered from cache, "
                   f"{ai['input_tokens']:,} tokens in, {ai['output_tokens']:,} out{cost}.")
    else:
        out.append("AI: off. Relevance and text came from the keyword rules, in English. The Chinese and Nepali pages "
                   "show the English text for these events until someone adds translations in this pull request.")
    return "\n".join(out) + "\n"
