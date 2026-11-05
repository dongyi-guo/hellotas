"""Reading the "Suggest an event" GitHub issue form (.github/ISSUE_TEMPLATE/suggest-event.yml).

GitHub turns a submitted form into Markdown: one "### <label>" heading per field, then the answer, with
"_No response_" for empty optional fields.
"""

from __future__ import annotations

import re

LINK = "Event link"
DETAILS = "Event details"
NOTE = "Why it's useful"


def parse(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current = None
    lines: list[str] = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            if current is not None:
                fields[current] = "\n".join(lines).strip()
            current, lines = heading.group(1), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        fields[current] = "\n".join(lines).strip()
    return {k: ("" if v == "_No response_" else v) for k, v in fields.items()}


def first_link(text: str) -> str:
    m = re.search(r"https?://[^\s<>()\"']+", text or "")
    return m.group(0).rstrip(".,;") if m else ""


def suggestion(body: str) -> dict[str, str]:
    """{'url', 'details', 'note'} from an issue body; url is '' when the form has no usable link."""
    fields = parse(body)
    return {
        "url": first_link(fields.get(LINK, "")),
        "details": fields.get(DETAILS, "")[:8000],
        "note": fields.get(NOTE, "")[:1000],
    }
