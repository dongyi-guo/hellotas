"""The weekly email digest: no account needed, double opt-in, one-click unsubscribe (RFC 8058).

Sending is triggered by POST /v1/admin/digest/send with the CRON_SECRET (a weekly GitHub Actions workflow calls
it), or by `hellotas-api send-digest` on the server.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import utcnow
from ..mail import Message, text, when
from ..models import Subscriber
from ..security import client_key, email_allowed, get_db, hash_token, new_token, normalise_email
from .common import lang_of, state

router = APIRouter(prefix="/v1", tags=["digest"])
TOPICS = {"cyber", "ai", "careers", "data", "development", "community", "ux"}


class Subscribe(BaseModel):
    email: str = Field(max_length=254)
    lang: str = "en"
    topics: list[str] = Field(default_factory=list, max_length=7)


def _page(title: str, message: str, site: str) -> HTMLResponse:
    """A tiny page for confirm and unsubscribe links opened from an email."""
    from html import escape
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        f"<title>{escape(title)}</title><body style='font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;"
        f"padding:0 1rem;color:#1E293B'><h1 style='color:#C8102E'>{escape(title)}</h1><p>{escape(message)}</p>"
        f"<p><a href='{escape(site)}' style='color:#C8102E'>Tasmania Welcome</a></p></body></html>")


@router.post("/digest/subscribe", status_code=202)
def subscribe(body: Subscribe, request: Request, db=Depends(get_db)):
    app = state(request)
    s = app.settings
    email = normalise_email(body.email)
    if not email_allowed(email, ["*"]):
        raise HTTPException(status_code=422, detail="That doesn't look like an email address.")
    app.limiter.hit("subscribe", client_key(request, s.secret_key, s.trust_proxy))
    lang = lang_of(body.lang)
    topics = ",".join(sorted(t for t in body.topics if t in TOPICS))
    token = new_token()
    sub = db.scalar(select(Subscriber).where(Subscriber.email == email))
    if sub is None:
        sub = Subscriber(email=email, lang=lang, topics=topics, token_hash=hash_token(token))
        db.add(sub)
    else:
        sub.lang, sub.topics, sub.token_hash = lang, topics, hash_token(token)
        if sub.status == "unsubscribed":
            sub.status = "pending"
    db.commit()
    if sub.status != "active":
        link = f"{str(request.base_url).rstrip('/')}/v1/digest/confirm?token={token}"
        app.mailer.send(Message(to=email, subject=text(lang, "confirm_subject"), text=text(lang, "confirm", link=link)))
    # Same answer either way, so the form can't be used to find out who is subscribed
    return {"ok": True}


@router.get("/digest/confirm", response_class=HTMLResponse)
def confirm(token: str, request: Request, db=Depends(get_db)):
    site = state(request).settings.site_url
    sub = db.scalar(select(Subscriber).where(Subscriber.token_hash == hash_token(token)))
    if sub is None:
        return _page("Link not recognised", "This confirmation link is out of date. Subscribe again on the site.", site)
    sub.status, sub.confirmed_at = "active", utcnow()
    db.commit()
    return _page("You're subscribed", "You'll get an email about ICT events every Monday morning.", site)


def _unsubscribe(token: str, request: Request, db) -> HTMLResponse:
    site = state(request).settings.site_url
    sub = db.scalar(select(Subscriber).where(Subscriber.token_hash == hash_token(token)))
    if sub is not None:
        sub.status = "unsubscribed"
        db.commit()
    return _page("Unsubscribed", "You won't get any more emails from Tasmania Welcome.", site)


@router.get("/digest/unsubscribe", response_class=HTMLResponse)
def unsubscribe_link(token: str, request: Request, db=Depends(get_db)):
    """The link in the email."""
    return _unsubscribe(token, request, db)


@router.post("/digest/unsubscribe", response_class=HTMLResponse)
def unsubscribe_one_click(token: str, request: Request, db=Depends(get_db)):
    """RFC 8058 one-click unsubscribe, used by Gmail and Outlook's own Unsubscribe button."""
    return _unsubscribe(token, request, db)


def upcoming(feed_events: dict, topics: str, now: datetime, days: int = 14) -> list[dict]:
    wanted = set(filter(None, topics.split(",")))
    out = []
    for e in feed_events.values():
        if e.get("date_tbc"):
            continue
        try:
            start = datetime.fromisoformat(e["start"])
            end = datetime.fromisoformat(e.get("end") or e["start"])
        except (KeyError, ValueError):
            continue
        if end < now or start > now + timedelta(days=days):
            continue
        if wanted and not wanted & set(e.get("topics") or []):
            continue
        out.append(e)
    return sorted(out, key=lambda e: e["start"])


def compose(e_list: list[dict], lang: str, site: str, unsubscribe_link: str) -> str:
    lines = [text(lang, "digest_intro")]
    if not e_list:
        lines.append(text(lang, "digest_none", link=f"{site}happening/"))
    for e in e_list:
        where = text(lang, "online") if e.get("format") == "online" else (e.get("location") or "")
        lines.append(f"\n{e['title']}\n{when(e['start'], lang, e.get('all_day', False))}"
                     + (f" · {where}" if where else "") + (f" · {e['cost']}" if e.get("cost") else "")
                     + (f"\n{e['summary']}" if e.get("summary") else "") + f"\n{e.get('page') or e.get('url')}")
    lines.append(text(lang, "digest_footer", site=site, unsubscribe=unsubscribe_link))
    return "\n".join(lines)


def send_all(app, db, base_url: str) -> dict:
    """One email per active subscriber. Each gets a fresh unsubscribe token."""
    now = datetime.now(timezone.utc)
    sent = 0
    for sub in db.scalars(select(Subscriber).where(Subscriber.status == "active")):
        events = upcoming(app.feed.events(sub.lang), sub.topics, now)
        token = new_token()
        sub.token_hash = hash_token(token)
        link = f"{base_url.rstrip('/')}/v1/digest/unsubscribe?token={token}"
        prefix = "" if sub.lang == "en" else f"{sub.lang}/"
        app.mailer.send(Message(
            to=sub.email, subject=text(sub.lang, "digest_subject"),
            text=compose(events, sub.lang, app.settings.site_url + prefix, link),
            headers={"List-Unsubscribe": f"<{link}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
        ))
        sub.last_sent_at = utcnow()
        sent += 1
    db.commit()
    return {"sent": sent}


@router.post("/admin/digest/send")
def send(request: Request, authorization: str = Header(default=""), db=Depends(get_db)):
    secret = state(request).settings.cron_secret
    if not secret or not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(status_code=403, detail="Wrong or missing CRON_SECRET.")
    return send_all(state(request), db, str(request.base_url))
