"""Small text helpers: cleaning, slugs, URL keys and title similarity."""

from __future__ import annotations

import html
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

# Query parameters that identify an event; everything else (tracking, access codes) is ignored when
# deciding whether two links point at the same event.
_ID_PARAMS = {"eventid", "eventkey", "id", "eid", "event", "e", "p"}

_SPACE = re.compile(r"[ \t  ​]+")
_FORMAT_MARKERS = re.compile(r"\s*[\[(](?:in[- ]?person|virtual|online|webinar|hybrid)[\])]\s*", re.I)
_SITE_SUFFIXES = re.compile(r"\s*[|\-–]\s*(?:humanitix|eventbrite|meetup|tickets?)\s*$", re.I)


def unescape(s: str) -> str:
    """Undo HTML entities, including double-escaped ones like &amp;amp; that some JSON-LD carries."""
    for _ in range(3):
        new = html.unescape(s)
        if new == s:
            break
        s = new
    return s


def clean(s: str | None) -> str:
    """One line of plain text: entities undone, whitespace collapsed."""
    if not s:
        return ""
    s = unescape(str(s))
    s = _SPACE.sub(" ", s.replace("\r", " ").replace("\n", " "))
    return s.strip()


def html_to_text(markup: str, limit: int | None = None) -> str:
    """Readable text from HTML, one block per line, without scripts, styles or navigation."""
    if not markup:
        return ""
    soup = BeautifulSoup(markup, "lxml")
    # Not <form> or <header>: ASP.NET sites (AISA's iMIS) wrap the whole page in one form, and some event pages
    # put the title and date in a header
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "iframe", "template"]):
        tag.decompose()
    lines = []
    for line in soup.get_text("\n").splitlines():
        line = clean(line)
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    text = "\n".join(lines)
    return text[:limit] if limit else text


def clean_title(title: str) -> str:
    title = clean(title)
    title = _SITE_SUFFIXES.sub("", title)
    title = _FORMAT_MARKERS.sub(" ", title).strip()
    return re.sub(r"\s{2,}", " ", title)


def no_em_dash(s: str, lang: str = "en") -> str:
    """House style: no em dashes in any language.

    Chinese: '——' becomes '，'. Other languages: a spaced dash becomes ', ' and a bare one a hyphen.
    """
    if not s:
        return s
    if lang == "zh":
        s = re.sub(r"\s*(?:——|—|―)\s*", "，", s)
        return s.replace("，，", "，")
    s = re.sub(r"\s+[—―]\s+", ", ", s)
    return s.replace("—", "-").replace("―", "-")


def first_sentences(text: str, max_words: int = 45) -> str:
    """The opening sentences of a description, cut at a sentence end within max_words."""
    text = clean(text)
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    # Sites often cut their own descriptions mid-sentence (Meetup's event data stops at ~160 characters)
    if len(sentences) > 1 and not re.search(r"[.!?]['\"’”)]?$", sentences[-1]):
        sentences = sentences[:-1]
    # Greetings like "Happy November, SecTalkers!" say nothing about the event
    while len(sentences) > 1 and sentences[0].endswith("!") and len(sentences[0].split()) <= 5:
        sentences = sentences[1:]
    # House style: no exclamation marks
    sentences = [s[:-1] + "." if s.endswith("!") else s for s in sentences]
    out: list[str] = []
    words = 0
    for sentence in sentences:
        n = len(sentence.split())
        if out and words + n > max_words:
            break
        out.append(sentence)
        words += n
        if words >= max_words * 0.6:
            break
    result = " ".join(out)
    if len(result.split()) > max_words:
        result = " ".join(result.split()[:max_words]).rstrip(",;:") + "…"
    return no_em_dash(result)


def slugify(s: str, max_words: int = 7) -> str:
    s = unicodedata.normalize("NFKD", unescape(s)).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", s)
    stop = {"the", "a", "an", "of", "for", "to", "in", "on", "at", "with", "and", "your", "our", "you"}
    keep = [w for w in words if w not in stop] or words
    return "-".join(keep[:max_words]).strip("-") or "event"


def url_key(url: str) -> str:
    """A key that is the same for two links to the same event page (scheme, www, tracking and case ignored)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/").lower()
    query = sorted((k.lower(), v) for k, v in parse_qsl(parts.query) if k.lower() in _ID_PARAMS)
    return urlunsplit(("", host, path, urlencode(query), "")).lstrip("/")


def _norm_title(title: str) -> str:
    title = unicodedata.normalize("NFKD", unescape(title)).lower()
    title = re.sub(r"\b20\d\d\b", " ", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return " ".join(title.split())


def title_similarity(a: str, b: str) -> float:
    """0 to 1. Uses both character order and shared words, so reordered titles still match."""
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 0.95
    seq = SequenceMatcher(None, na, nb).ratio()
    wa, wb = set(na.split()), set(nb.split())
    jaccard = len(wa & wb) / len(wa | wb)
    return max(seq, jaccard)
