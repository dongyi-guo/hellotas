"""Data passed between the steps of a run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# The values the site understands (layouts/happening/list.html and i18n/*.yaml)
TYPES = (
    "webinar", "workshop", "forum", "talk", "meetup", "conference", "hackathon", "networking", "awards",
    "summit", "expo", "festival",
)
FORMATS = ("online", "in_person", "hybrid")
TOPICS = ("cyber", "ai", "careers", "data", "development", "community", "ux")
LANGS = ("en", "zh", "ne")


@dataclass
class RawEvent:
    """An event as a source describes it, before any judging or writing."""

    source: str
    url: str
    title: str
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    description: str = ""
    location_name: str = ""
    address: str = ""
    locality: str = ""
    region: str = ""
    country: str = ""
    online: bool | None = None
    attendance: str = ""  # online, in_person or hybrid when the source says so
    host: str = ""
    cost: str = ""  # cost as the source words it, e.g. "Free" or "$20 for non-members"
    free: bool | None = None
    images: list[str] = field(default_factory=list)
    status: str = "scheduled"  # scheduled, cancelled, postponed or moved_online
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # source-specific facts used by the rules (e.g. ACS event type)

    @property
    def text(self) -> str:
        """Everything worth searching for keywords."""
        return " ".join([self.title, self.description, self.host, " ".join(self.tags)])


@dataclass
class Judgement:
    relevant: bool
    score: int
    reason: str
    by: str  # "ai", "rules" or "person" (someone suggested it)


@dataclass
class Proposal:
    """A new event ready to be written to data/happening/<slug>.yaml."""

    raw: RawEvent
    slug: str
    fields: dict
    judgement: Judgement
    written_by: str  # "ai" or "rules"
    image_path: str = ""  # file written under static/
    image_borrowed: str = ""  # set when the organiser's picture couldn't be used, e.g. "the site's default picture"
    file_path: str = ""


@dataclass
class Skip:
    raw: RawEvent
    why: str
    detail: str = ""
