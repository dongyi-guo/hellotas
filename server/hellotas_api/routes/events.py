"""Interested / going counts, and event buddies ("Don't go alone").

Buddies are visible only to signed-in users, and only by display name, course and note. Asking someone sends them
an email; email addresses are shared only when the person asked accepts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import utcnow
from ..mail import Message, text, when
from ..models import BuddyIntro, BuddyListing, EventMark, User
from ..security import current_user, get_db, optional_user
from .common import check_event_id, clean_text, state

router = APIRouter(prefix="/v1", tags=["events"])


def _event(request: Request, event_id: str, lang: str = "en") -> dict:
    check_event_id(event_id)
    event = state(request).feed.get(event_id, lang)
    if event is None:
        raise HTTPException(status_code=404, detail="No such event on the site.")
    return event


@router.get("/events/stats")
def stats(request: Request, ids: str = "", user: User | None = Depends(optional_user), db=Depends(get_db)):
    """Public counts per event; with a session, also the caller's own mark and buddy listing."""
    wanted = [i for i in ids.split(",") if i][:200] or list(state(request).feed.events().keys())
    out = {i: {"interested": 0, "going": 0, "buddies": 0} for i in wanted}
    for event_id, status, n in db.execute(select(EventMark.event_id, EventMark.status, func.count())
                                          .where(EventMark.event_id.in_(wanted))
                                          .group_by(EventMark.event_id, EventMark.status)):
        out[event_id][status] = n
    for event_id, n in db.execute(select(BuddyListing.event_id, func.count()).where(
            BuddyListing.event_id.in_(wanted)).group_by(BuddyListing.event_id)):
        out[event_id]["buddies"] = n
    if user:
        for mark in db.scalars(select(EventMark).where(EventMark.user_id == user.id,
                                                       EventMark.event_id.in_(wanted))):
            out[mark.event_id]["mine"] = mark.status
        for listing in db.scalars(select(BuddyListing).where(BuddyListing.user_id == user.id,
                                                             BuddyListing.event_id.in_(wanted))):
            out[listing.event_id]["my_buddy_note"] = listing.note
    return {"events": out}


class Mark(BaseModel):
    status: str = Field(pattern="^(interested|going|none)$")


@router.put("/events/{event_id}/mark")
def mark(event_id: str, body: Mark, request: Request, user: User = Depends(current_user), db=Depends(get_db)):
    event = _event(request, event_id, user.lang)
    existing = db.scalar(select(EventMark).where(EventMark.user_id == user.id, EventMark.event_id == event_id))
    if body.status == "none":
        if existing:
            db.delete(existing)
    elif existing:
        existing.status = body.status
    else:
        db.add(EventMark(user_id=user.id, event_id=event_id, status=body.status, title=event.get("title", "")[:300],
                         start=event.get("start", ""), end=event.get("end", ""), host=event.get("host", "")[:200]))
    db.commit()
    return stats(request, ids=event_id, user=user, db=db)["events"][event_id]


# -- buddies --------------------------------------------------------------------------------------------------

class BuddyNote(BaseModel):
    note: str = Field(default="", max_length=280)


class Ask(BaseModel):
    message: str = Field(default="", max_length=280)


@router.get("/events/{event_id}/buddies")
def buddies(event_id: str, request: Request, user: User = Depends(current_user), db=Depends(get_db)):
    _event(request, event_id, user.lang)
    asked = {i.to_user_id: i.status for i in db.scalars(select(BuddyIntro).where(
        BuddyIntro.from_user_id == user.id, BuddyIntro.event_id == event_id))}
    out = []
    for listing in db.scalars(select(BuddyListing).where(BuddyListing.event_id == event_id)
                              .order_by(BuddyListing.created_at)):
        u = listing.user
        out.append({"id": listing.id, "name": u.public_name, "course": u.course, "languages": u.languages,
                    "note": listing.note, "mine": u.id == user.id, "asked": asked.get(u.id, "")})
    return {"buddies": out}


@router.put("/events/{event_id}/buddy")
def list_me(event_id: str, body: BuddyNote, request: Request, user: User = Depends(current_user),
            db=Depends(get_db)):
    _event(request, event_id, user.lang)
    listing = db.scalar(select(BuddyListing).where(BuddyListing.user_id == user.id,
                                                   BuddyListing.event_id == event_id))
    note = clean_text(body.note, 280)
    if listing:
        listing.note = note
    else:
        db.add(BuddyListing(user_id=user.id, event_id=event_id, note=note))
    db.commit()
    return buddies(event_id, request, user, db)


@router.delete("/events/{event_id}/buddy")
def unlist_me(event_id: str, request: Request, user: User = Depends(current_user), db=Depends(get_db)):
    check_event_id(event_id)
    listing = db.scalar(select(BuddyListing).where(BuddyListing.user_id == user.id,
                                                   BuddyListing.event_id == event_id))
    if listing:
        db.delete(listing)
        db.commit()
    return {"listed": False}


@router.post("/events/{event_id}/buddies/{listing_id}/ask", status_code=201)
def ask(event_id: str, listing_id: int, body: Ask, request: Request, user: User = Depends(current_user),
        db=Depends(get_db)):
    app = state(request)
    listing = db.get(BuddyListing, listing_id)
    if listing is None or listing.event_id != event_id:
        raise HTTPException(status_code=404, detail="That person is no longer looking for company.")
    if listing.user_id == user.id:
        raise HTTPException(status_code=400, detail="That's you.")
    app.limiter.hit("ask", str(user.id))
    existing = db.scalar(select(BuddyIntro).where(BuddyIntro.from_user_id == user.id,
                                                  BuddyIntro.to_user_id == listing.user_id,
                                                  BuddyIntro.event_id == event_id))
    if existing:
        return {"id": existing.id, "status": existing.status}
    to = listing.user
    event = _event(request, event_id, to.lang)
    message = clean_text(body.message, 280)
    intro = BuddyIntro(event_id=event_id, from_user_id=user.id, to_user_id=to.id, message=message)
    db.add(intro)
    db.commit()
    s = app.settings
    prefix = "" if to.lang == "en" else f"{to.lang}/"
    app.mailer.send(Message(
        to=to.email,
        subject=text(to.lang, "ask_subject", name=user.public_name, event=event["title"]),
        text=text(to.lang, "ask", to=to.public_name, name=user.public_name, event=event["title"],
                  when=when(event["start"], to.lang, event.get("all_day", False)),
                  message=f"“{message}”" if message else "", link=f"{s.site_url}{prefix}account/#buddies"),
    ))
    return {"id": intro.id, "status": intro.status}


class Answer(BaseModel):
    accept: bool


@router.post("/intros/{intro_id}")
def answer(intro_id: int, body: Answer, request: Request, user: User = Depends(current_user), db=Depends(get_db)):
    app = state(request)
    intro = db.get(BuddyIntro, intro_id)
    if intro is None or intro.to_user_id != user.id:
        raise HTTPException(status_code=404, detail="No such request.")
    if intro.status != "pending":
        return {"id": intro.id, "status": intro.status}
    intro.status = "accepted" if body.accept else "declined"
    intro.responded_at = utcnow()
    db.commit()
    if body.accept:
        a, b = intro.from_user, intro.to_user
        for person, other in ((a, b), (b, a)):
            event = app.feed.get(intro.event_id, person.lang) or {"title": intro.event_id, "start": "", "page": ""}
            app.mailer.send(Message(
                to=person.email,
                subject=text(person.lang, "match_subject", event=event["title"]),
                text=text(person.lang, "match", to=person.public_name, other=other.public_name, email=other.email,
                          event=event["title"], when=when(event.get("start", ""), person.lang,
                                                          event.get("all_day", False)),
                          event_link=event.get("page", "")),
            ))
    return {"id": intro.id, "status": intro.status}
