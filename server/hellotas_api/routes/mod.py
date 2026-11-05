"""Moderation: the queue of posts, reports and website suggestions; roles; usage numbers."""

from __future__ import annotations

from datetime import timedelta

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import utcnow
from ..github import create_issue
from ..models import BuddyIntro, BuddyListing, EventMark, Post, Report, Subscriber, Suggestion, User
from ..security import admin, get_db, moderator
from .common import state
from .posts import post_out

router = APIRouter(prefix="/v1/mod", tags=["moderation"])


class Decision(BaseModel):
    action: str = Field(pattern="^(approve|reject|hide)$")


class SuggestionDecision(BaseModel):
    action: str = Field(pattern="^(forward|reject)$")


class Role(BaseModel):
    role: str = Field(pattern="^(member|moderator|admin)$")


def suggestion_out(s: Suggestion) -> dict:
    return {"id": s.id, "url": s.url, "details": s.details, "note": s.note, "status": s.status,
            "issue_url": s.issue_url, "by": s.user.public_name if s.user else "",
            "created_at": s.created_at.isoformat() + "Z"}


@router.get("/queue")
def queue(user: User = Depends(moderator), db=Depends(get_db)):
    pending = [post_out(p, full=True) for p in db.scalars(select(Post).where(Post.status == "pending")
                                                          .order_by(Post.created_at))]
    reports = []
    for r in db.scalars(select(Report).where(Report.resolved.is_(False)).order_by(Report.created_at)):
        post = db.get(Post, r.post_id)
        if post:
            reports.append({"id": r.id, "reason": r.reason, "post": post_out(post, full=True)})
    suggestions = [suggestion_out(s) for s in db.scalars(select(Suggestion).where(Suggestion.status == "pending")
                                                         .order_by(Suggestion.created_at))]
    return {"posts": pending, "reports": reports, "suggestions": suggestions}


@router.post("/posts/{post_id}")
def decide(post_id: int, body: Decision, user: User = Depends(moderator), db=Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="No such post.")
    post.status = {"approve": "approved", "reject": "rejected", "hide": "hidden"}[body.action]
    post.moderated_at, post.moderated_by = utcnow(), user.id
    for r in db.scalars(select(Report).where(Report.post_id == post_id)):
        r.resolved = True
    db.commit()
    return post_out(post, full=True)


@router.post("/reports/{report_id}/dismiss")
def dismiss(report_id: int, user: User = Depends(moderator), db=Depends(get_db)):
    r = db.get(Report, report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="No such report.")
    r.resolved = True
    db.commit()
    return {"dismissed": True}


@router.post("/suggestions/{suggestion_id}")
def decide_suggestion(suggestion_id: int, body: SuggestionDecision, request: Request,
                      user: User = Depends(moderator), db=Depends(get_db)):
    s = db.get(Suggestion, suggestion_id)
    if s is None:
        raise HTTPException(status_code=404, detail="No such suggestion.")
    if body.action == "reject":
        s.status = "rejected"
    else:
        forward(request, s, f"{user.public_name} (moderator)")
    db.commit()
    return suggestion_out(s)


def forward(request: Request, s: Suggestion, who: str) -> None:
    """Open the GitHub issue the collector picks up. Leaves the suggestion pending if GitHub isn't set up."""
    app = state(request)
    cfg = app.settings
    if not cfg.github_token:
        return
    try:
        s.issue_url = create_issue(cfg.github_repo, cfg.github_token, s.url, s.details, s.note, who,
                                   session=app.http)
        s.status = "forwarded"
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"GitHub didn't accept the issue: {exc}") from exc


@router.get("/stats")
def stats(user: User = Depends(moderator), db=Depends(get_db)):
    """The numbers that say whether the community features are used (docs/research/platform-v2.md)."""
    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0
    month = utcnow() - timedelta(days=30)
    return {
        "users": count(User), "users_new_30_days": count(User, User.created_at >= month),
        "users_active_30_days": count(User, User.last_seen_at >= month),
        "event_marks": count(EventMark), "going": count(EventMark, EventMark.status == "going"),
        "buddy_listings": count(BuddyListing), "buddy_requests": count(BuddyIntro),
        "buddy_requests_accepted": count(BuddyIntro, BuddyIntro.status == "accepted"),
        "posts_approved": count(Post, Post.status == "approved"), "posts_pending": count(Post, Post.status == "pending"),
        "digest_subscribers": count(Subscriber, Subscriber.status == "active"),
        "suggestions": count(Suggestion), "suggestions_forwarded": count(Suggestion, Suggestion.status == "forwarded"),
    }


@router.get("/users")
def users(q: str = "", user: User = Depends(admin), db=Depends(get_db)):
    query = select(User).order_by(User.created_at.desc()).limit(50)
    if q:
        query = query.where(User.email.contains(q.lower(), autoescape=True))
    return {"users": [{"id": u.id, "email": u.email, "display_name": u.display_name, "role": u.role}
                      for u in db.scalars(query)]}


@router.post("/users/{user_id}/role")
def set_role(user_id: int, body: Role, user: User = Depends(admin), db=Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No such user.")
    if target.id == user.id and body.role != "admin":
        raise HTTPException(status_code=400, detail="Ask another admin to change your own role.")
    target.role = body.role
    db.commit()
    return {"id": target.id, "role": target.role}
