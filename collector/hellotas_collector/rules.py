"""Judging and describing events without AI: keyword rules tuned on the events the team picked by hand.

The AI (ai.py) does this better; these rules keep the collector useful with no API key, and are the fallback when
the AI is unavailable. They are deliberately cautious: a missed event can still be suggested by a person, while a
wrong one shows up on the site.
"""

from __future__ import annotations

import re

from .model import FORMATS, TOPICS, TYPES, Judgement, RawEvent
from .text import clean, first_sentences, no_em_dash

TOPIC_WORDS = {
    "cyber": r"cyber|security|infosec|\bctf\b|hacking|hacker|privacy|phishing|ransomware|owasp|sectalks|\bpki\b|"
             r"threat|malware|esafety|incident response|\bsoc\b|penetration",
    "ai": r"\bai\b|artificial intelligence|machine learning|\bml\b|\bllms?\b|gemini|\bgpt|genai|generative|"
          r"\bagents?\b|agentic|copilot|vertex|neural|deep learning",
    "careers": r"career|\bjobs?\b|graduate|internship|resume|\bcv\b|interview|employ|recruit|professional year|"
               r"mentor|job search|work experience|early career|emerging professional",
    "data": r"\bdata\b|analytics|dashboard|looker|power bi|\bsql\b|database|visuali[sz]ation|statistic",
    "development": r"developer|\bdev\b|coding|programming|software|android|\bios\b|flutter|\bweb\b|cloud|devops|"
                   r"github|\bapi\b|\bapps?\b|hackathon|software engineering|open source|kotlin|python|javascript|"
                   r"devfest",
    "community": r"community|meetup|social|networking|women in|inclusion|volunteer|awards|celebrat|drinks|"
                 r"mixer|sundowner|club",
    "ux": r"\bux\b|\bui\b|user experience|game|gaming|accessib|design thinking|product design",
}

# Words that settle an event's type on their own, then weaker hints (first match wins in each list)
STRONG_TYPES = [
    ("hackathon", r"hackathon|hack day|\bctf\b|capture the flag"),
    ("awards", r"\bawards?\b"),
    ("webinar", r"\bwebinars?\b"),
    ("workshop", r"\bworkshops?\b|hands-on|hands on|masterclass|bootcamp|codelab"),
    ("conference", r"\bconference\b|cybercon|devfest|\bsummit\b"),
    ("expo", r"\bexpo\b|\bshowcase\b|careers? fair"),
    ("festival", r"\bfestival\b|\bfest\b"),
]
WEAK_TYPES = [
    ("networking", r"\bnetworking\b|\bdrinks\b|\bmixer\b|sundowner|\bbreakfast\b|\bcoffee\b|celebration"),
    ("forum", r"\bforum\b|\bpanel\b|roundtable|\bconversation\b|symposium"),
    ("meetup", r"\bmeetups?\b|meet-up|social night|user group"),
    ("talk", r"\btalks?\b|\bpresentation\b|\blecture\b|\bseminar\b|\binsights\b|fireside chat"),
]

# Signals that an event is for ICT students and early-career people
STUDENT_WORDS = (r"student|graduate|early career|emerging professional|beginner|new to|first job|career|"
                 r"job|internship|young professional|\buni\b|university")
# Signals that an event is for someone else, or is a paid course rather than an event
NOT_FOR_US = (r"\bkids\b|children|school holiday|for seniors|\blego\b|annual general meeting|\bagm\b|"
              r"board directors|c-suite|executive breakfast|short course|masterclass|\btrivia\b|"
              r"parliamentary|premier|minister|members['’]? only|digital help|digital mentor|drop[- ]in")

_TRUST_BASE = {"high": 60, "medium": 40, "low": 20}


def _hits(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, re.I))


def gist(ev: RawEvent) -> str:
    """What the rules judge by: the title and the short description. Full event pages mention so many topics in
    passing (sponsors, speaker bios) that keywords from the whole text say little about what the event is."""
    short = ev.extra.get("short_description") or ev.description[:500]
    return " ".join([ev.title, ev.title, short, ev.host, " ".join(ev.tags)])


def topics_for(ev: RawEvent) -> list[str]:
    text = gist(ev)
    scored = sorted(((_hits(rx, text), t) for t, rx in TOPIC_WORDS.items()), reverse=True)
    topics = [t for n, t in scored if n > 0][:3]
    for t in ev.extra.get("default_topics", []):
        if t in TOPICS and t not in topics and len(topics) < 3:
            topics.append(t)
    return [t for t in TOPICS if t in topics] or ["community"]


def type_for(ev: RawEvent) -> str:
    """Strong words in the title, then online (a webinar), then the source's default, then weaker hints."""
    for name, rx in STRONG_TYPES:
        if re.search(rx, ev.title, re.I):
            return name
    if format_for(ev) == "online":
        return "webinar"
    default = ev.extra.get("default_type")
    if default in TYPES:
        return default
    for text in (ev.title, ev.description[:600]):
        for name, rx in STRONG_TYPES + WEAK_TYPES:
            if re.search(rx, text, re.I):
                return name
    return "talk"


def format_for(ev: RawEvent) -> str:
    if ev.attendance in FORMATS:
        return ev.attendance
    blob = " ".join([ev.title, ev.location_name, ev.description[:400]])
    online = bool(ev.online) or bool(re.search(r"\b(online|webinar|virtual|zoom|teams|livestream)\b", blob, re.I))
    in_person = bool(ev.location_name or ev.address) and not re.fullmatch(
        r"(?i)\s*(online|virtual|zoom|webinar|online webinar)\s*", ev.location_name or "")
    if online and in_person:
        return "hybrid"
    return "online" if online else "in_person"


def judge(ev: RawEvent) -> Judgement:
    """A relevance score from 0 to 100 and the main reasons for it."""
    text = gist(ev)
    score = _TRUST_BASE.get(ev.extra.get("trust", "medium"), 40)
    why = [f"{ev.extra.get('trust', 'medium')}-trust source"]
    topic_hits = [t for t, rx in TOPIC_WORDS.items() if t != "community" and _hits(rx, text)]
    if topic_hits:
        score += min(30, 10 * len(topic_hits))
        why.append("ICT topics: " + ", ".join(topic_hits))
    if re.search(STUDENT_WORDS, text, re.I):
        score += 15
        why.append("aimed at students or early careers")
    fmt = format_for(ev)
    if fmt == "online":
        score += 5
    elif ev.region == "TAS":
        score += 10
        why.append("in Tasmania")
    elif ev.region:
        score -= 40
        why.append(f"in person in {ev.region}, not Tasmania")
    else:
        why.append("location unclear")
    bad = sorted({m.lower() for m in re.findall(NOT_FOR_US, text, re.I)})
    if bad:
        score -= 30 * min(2, len(bad))
        why.append("not for students: " + ", ".join(bad))
    if ev.extra.get("members_only") and ev.extra.get("trust") != "high":
        why.append("members only")
    if ev.status == "cancelled":
        score = 0
        why.append("cancelled")
    score = max(0, min(100, score))
    return Judgement(relevant=score >= 50, score=score, reason="; ".join(why), by="rules")


def location_text(ev: RawEvent) -> str:
    if format_for(ev) == "online":
        return ""
    parts = []
    for p in [ev.location_name, *ev.address.split(", ")]:
        p = clean(p)
        if p and not any(p.lower() in q.lower() for q in parts):
            parts.append(p)
    return ", ".join(parts[:4])


def cost_text(ev: RawEvent) -> str:
    if ev.cost:
        return no_em_dash(ev.cost)
    if ev.free:
        return "Free"
    return "See the official page"


# Fixed wording the rules can write in all three languages
COST_PHRASES = {
    "Free": {"zh": "免费", "ne": "निःशुल्क"},
    "See the official page": {"zh": "详见官方页面", "ne": "आधिकारिक पृष्ठ हेर्नुहोस्"},
    "Free for AISA members": {"zh": "AISA会员免费", "ne": "AISA सदस्यहरूका लागि निःशुल्क"},
}


def write(ev: RawEvent) -> dict:
    """The data fields for an event, written by rules: English only (the site falls back to English)."""
    cost = cost_text(ev)
    fields = {
        "title": {"en": no_em_dash(ev.title)},
        "type": type_for(ev),
        "format": format_for(ev),
        "topics": topics_for(ev),
        "host": ev.host or "",
        "location": {"en": no_em_dash(location_text(ev))},
        "cost": {"en": cost, **COST_PHRASES.get(cost, {})},
        "summary": {"en": first_sentences(ev.description) or no_em_dash(ev.title)},
    }
    if not fields["location"]["en"]:
        del fields["location"]
    return fields
