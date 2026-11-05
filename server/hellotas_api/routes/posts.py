"""Wish Wall, Achievement Wall and the opportunities board (upstream issue #24).

Everything posted waits for a moderator. The public sees approved posts with the author's display name only.
Opportunities carry who can apply (visa conditions) and a closing date, after which they drop off the board.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..models import OPPORTUNITY_TYPES, POST_KINDS, REACTIONS, WORK_RIGHTS, Post, Reaction, Report, User
from ..security import client_key, current_user, get_db, optional_user
from .common import clean_text, clean_url, state

router = APIRouter(prefix="/v1/posts", tags=["posts"])


class NewPost(BaseModel):
    kind: str = Field(pattern="^(wish|achievement|opportunity)$")
    title: str = Field(min_length=3, max_length=140)
    body: str = Field(default="", max_length=2000)
    link: str = Field(default="", max_length=500)
    # Opportunities only
    organisation: str = Field(default="", max_length=120)
    opportunity_type: str = Field(default="other", max_length=20)
    work_rights: str = Field(default="anyone", max_length=20)
    closes_on: date | None = None


class ReportBody(BaseModel):
    reason: str = Field(default="", max_length=500)


def post_out(p: Post, reactions: int = 0, mine: bool = False, reacted: bool = False, full: bool = False) -> dict:
    out = {"id": p.id, "kind": p.kind, "title": p.title, "body": p.body, "link": p.link, "meta": p.meta or {},
           "author": p.user.public_name if p.user else "", "created_at": p.created_at.isoformat() + "Z",
           "reactions": reactions, "reaction": REACTIONS[p.kind], "reacted": reacted, "mine": mine}
    if full:
        out.update(status=p.status, author_email=p.user.email if p.user else "")
    return out


def _open(p: Post) -> bool:
    closes = (p.meta or {}).get("closes_on")
    return not closes or closes >= date.today().isoformat()


@router.get("")
def list_posts(kind: str, sort: str = "new", user: User | None = Depends(optional_user), db=Depends(get_db)):
    if kind not in POST_KINDS:
        raise HTTPException(status_code=404, detail="No such wall.")
    posts = list(db.scalars(select(Post).where(Post.kind == kind, Post.status == "approved")
                            .order_by(Post.created_at.desc()).limit(300)))
    ids = [p.id for p in posts]
    counts = dict(db.execute(select(Reaction.post_id, func.count()).where(Reaction.post_id.in_(ids))
                             .group_by(Reaction.post_id)).all()) if ids else {}
    mine = set()
    if user and ids:
        mine = set(db.scalars(select(Reaction.post_id).where(Reaction.user_id == user.id, Reaction.post_id.in_(ids))))
    out = [post_out(p, counts.get(p.id, 0), bool(user and p.user_id == user.id), p.id in mine)
           for p in posts if kind != "opportunity" or _open(p)]
    if sort == "top":
        out.sort(key=lambda p: -p["reactions"])  # stable: ties stay newest first
    pending = []
    if user:  # your own posts still waiting for a moderator
        pending = [post_out(p, mine=True, full=True) for p in db.scalars(
            select(Post).where(Post.kind == kind, Post.user_id == user.id, Post.status == "pending"))]
    return {"posts": out, "pending": pending}


@router.post("", status_code=201)
def create(body: NewPost, request: Request, user: User = Depends(current_user), db=Depends(get_db)):
    state(request).limiter.hit("post", str(user.id))
    meta = {}
    if body.kind == "opportunity":
        if body.opportunity_type not in OPPORTUNITY_TYPES or body.work_rights not in WORK_RIGHTS:
            raise HTTPException(status_code=422, detail="Choose the type and who can apply.")
        if not body.link:
            raise HTTPException(status_code=422, detail="Opportunities need a link to the details.")
        meta = {"organisation": clean_text(body.organisation, 120), "type": body.opportunity_type,
                "work_rights": body.work_rights, "closes_on": body.closes_on.isoformat() if body.closes_on else ""}
    post = Post(kind=body.kind, user_id=user.id, title=clean_text(body.title, 140),
                body=clean_text(body.body, 2000, multiline=True), link=clean_url(body.link), meta=meta,
                status="approved" if user.is_moderator else "pending")
    db.add(post)
    db.commit()
    return post_out(post, mine=True, full=True)


@router.post("/{post_id}/react")
def react(post_id: int, user: User = Depends(current_user), db=Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None or post.status != "approved":
        raise HTTPException(status_code=404, detail="No such post.")
    existing = db.scalar(select(Reaction).where(Reaction.post_id == post_id, Reaction.user_id == user.id))
    if existing:
        db.delete(existing)
    else:
        db.add(Reaction(post_id=post_id, user_id=user.id))
    db.commit()
    n = db.scalar(select(func.count()).select_from(Reaction).where(Reaction.post_id == post_id))
    return {"reactions": n, "reacted": existing is None}


@router.post("/{post_id}/report", status_code=201)
def report(post_id: int, body: ReportBody, request: Request, user: User = Depends(current_user),
           db=Depends(get_db)):
    s = state(request)
    s.limiter.hit("report", client_key(request, s.settings.secret_key, s.settings.trust_proxy))
    if db.get(Post, post_id) is None:
        raise HTTPException(status_code=404, detail="No such post.")
    db.add(Report(post_id=post_id, user_id=user.id, reason=clean_text(body.reason, 500)))
    db.commit()
    return {"reported": True}


@router.delete("/{post_id}")
def remove(post_id: int, user: User = Depends(current_user), db=Depends(get_db)):
    post = db.get(Post, post_id)
    if post is None or (post.user_id != user.id and not user.is_moderator):
        raise HTTPException(status_code=404, detail="No such post.")
    db.delete(post)
    db.commit()
    return {"deleted": True}
