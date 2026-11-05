"""The signed-in person: profile, data export and deletion, checklist, their events and buddy requests."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select

from ..models import (BuddyIntro, BuddyListing, ChecklistItem, EventMark, Post, Reaction, Report, Session,
                      Suggestion, User)
from ..security import current_user, get_db
from .common import clean_text, lang_of, state

router = APIRouter(prefix="/v1/me", tags=["me"])
CHECKLIST_ID = r"^[a-z0-9][a-z0-9-]{0,79}$"


def user_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "course": user.course,
            "languages": user.languages, "role": user.role, "lang": user.lang,
            "created_at": user.created_at.isoformat() + "Z"}


class Profile(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    course: str | None = Field(default=None, max_length=100)
    languages: str | None = Field(default=None, max_length=100)
    lang: str | None = None


@router.get("")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.patch("")
def update_me(body: Profile, user: User = Depends(current_user), db=Depends(get_db)):
    if body.display_name is not None:
        user.display_name = clean_text(body.display_name, 60) or user.public_name
    if body.course is not None:
        user.course = clean_text(body.course, 100)
    if body.languages is not None:
        user.languages = clean_text(body.languages, 100)
    if body.lang is not None:
        user.lang = lang_of(body.lang)
    db.commit()
    return user_out(user)


@router.get("/export")
def export(user: User = Depends(current_user), db=Depends(get_db)):
    """Everything held about this person, as JSON."""
    def rows(model, *where):
        out = []
        for r in db.scalars(select(model).where(*where)):
            out.append({c.name: (getattr(r, c.name).isoformat() if hasattr(getattr(r, c.name), "isoformat")
                                 else getattr(r, c.name)) for c in model.__table__.columns
                        if c.name not in ("token_hash",)})
        return out
    return {
        "account": user_out(user),
        "events": rows(EventMark, EventMark.user_id == user.id),
        "buddy_listings": rows(BuddyListing, BuddyListing.user_id == user.id),
        "buddy_requests": rows(BuddyIntro, or_(BuddyIntro.from_user_id == user.id, BuddyIntro.to_user_id == user.id)),
        "posts": rows(Post, Post.user_id == user.id),
        "reactions": rows(Reaction, Reaction.user_id == user.id),
        "reports": rows(Report, Report.user_id == user.id),
        "checklist": rows(ChecklistItem, ChecklistItem.user_id == user.id),
        "suggestions": rows(Suggestion, Suggestion.user_id == user.id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


@router.delete("")
def delete_me(user: User = Depends(current_user), db=Depends(get_db)):
    """Deletes the account and everything attached to it. Approved posts are removed too, not just anonymised."""
    for model, column in ((Session, Session.user_id), (EventMark, EventMark.user_id),
                          (BuddyListing, BuddyListing.user_id), (Reaction, Reaction.user_id),
                          (ChecklistItem, ChecklistItem.user_id), (Post, Post.user_id)):
        db.execute(delete(model).where(column == user.id))
    db.execute(delete(BuddyIntro).where(or_(BuddyIntro.from_user_id == user.id, BuddyIntro.to_user_id == user.id)))
    db.execute(delete(Report).where(Report.user_id == user.id))
    for s in db.scalars(select(Suggestion).where(Suggestion.user_id == user.id)):
        s.user_id = None
    db.delete(user)
    db.commit()
    return {"deleted": True}


# -- checklist ------------------------------------------------------------------------------------------------

class ChecklistUpdate(BaseModel):
    done: list[str] = Field(default_factory=list, max_length=200)
    undone: list[str] = Field(default_factory=list, max_length=200)


@router.get("/checklist")
def checklist(user: User = Depends(current_user), db=Depends(get_db)):
    items = db.scalars(select(ChecklistItem).where(ChecklistItem.user_id == user.id))
    return {"done": sorted(i.item_id for i in items)}


@router.post("/checklist")
def update_checklist(body: ChecklistUpdate, user: User = Depends(current_user), db=Depends(get_db)):
    """Merge ticks from the browser: `done` items are added, `undone` ones removed."""
    valid = re.compile(CHECKLIST_ID)
    have = {i.item_id: i for i in db.scalars(select(ChecklistItem).where(ChecklistItem.user_id == user.id))}
    for item in {i for i in body.done if valid.match(i)} - set(have):
        db.add(ChecklistItem(user_id=user.id, item_id=item))
    for item in set(body.undone) & set(have):
        db.delete(have[item])
    db.commit()
    return checklist(user, db)


# -- my events and buddy requests -------------------------------------------------------------------------------

@router.get("/events")
def my_events(request: Request, user: User = Depends(current_user), db=Depends(get_db)):
    """Interested and going, with 'went' for events that are over: a record to copy into a CV or LinkedIn."""
    feed = state(request).feed.events(user.lang)
    now = datetime.now(timezone.utc)
    out = []
    for mark in db.scalars(select(EventMark).where(EventMark.user_id == user.id)):
        live = feed.get(mark.event_id)
        if live:  # keep the stored copy current while the event is on the site
            mark.title, mark.start, mark.end, mark.host = (live.get("title", "")[:300], live.get("start", ""),
                                                           live.get("end", ""), live.get("host", "")[:200])
        try:
            over = datetime.fromisoformat(mark.end or mark.start) < now
        except ValueError:
            over = False
        status = "went" if over and mark.status == "going" else mark.status
        out.append({"event_id": mark.event_id, "status": status, "title": mark.title, "start": mark.start,
                    "end": mark.end, "host": mark.host, "page": (live or {}).get("page", ""),
                    "url": (live or {}).get("url", "")})
    db.commit()
    out.sort(key=lambda e: e["start"])
    return {"events": out}


@router.get("/intros")
def my_intros(request: Request, user: User = Depends(current_user), db=Depends(get_db)):
    feed = state(request).feed.events(user.lang)
    rows = db.scalars(select(BuddyIntro).where(
        or_(BuddyIntro.to_user_id == user.id, BuddyIntro.from_user_id == user.id)).order_by(BuddyIntro.created_at))
    out = []
    for intro in rows:
        incoming = intro.to_user_id == user.id
        other = intro.from_user if incoming else intro.to_user
        event = feed.get(intro.event_id, {})
        item = {"id": intro.id, "direction": "incoming" if incoming else "outgoing", "status": intro.status,
                "event_id": intro.event_id, "event_title": event.get("title", intro.event_id),
                "event_page": event.get("page", ""), "name": other.public_name, "course": other.course,
                "message": intro.message}
        if intro.status == "accepted":
            item["email"] = other.email  # both agreed
        out.append(item)
    return {"intros": out}
