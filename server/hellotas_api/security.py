"""Tokens and the signed-in user.

Sign-in links and sessions are random 32-byte tokens. Only their SHA-256 hashes are stored, so a copy of the
database can't be used to sign in. (A fast hash is right here: the tokens are random, not passwords people chose.)
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from .db import utcnow
from .models import Session, User

EMAIL_RX = re.compile(r"^[A-Za-z0-9._%+'-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return email.strip().lower()


def default_name(email: str) -> str:
    """A starting display name that doesn't give the address away: the first word of the local part
    ("bob" from bob.rai@...), or "UTAS student" when that looks like an ID. People change it on /account/."""
    first = re.split(r"[._+-]", email.split("@", 1)[0])[0]
    if len(first) < 2 or any(ch.isdigit() for ch in first):
        return "UTAS student"
    return first[:30].capitalize()


def email_allowed(email: str, domains: list[str]) -> bool:
    if not EMAIL_RX.match(email):
        return False
    if "*" in domains:
        return True
    domain = email.rsplit("@", 1)[1]
    return any(domain == d or domain.endswith("." + d) for d in domains)


def client_key(request: Request, secret: str, trust_proxy: bool) -> str:
    """A keyed hash of the visitor's IP address: enough to rate-limit, without storing the address."""
    ip = request.client.host if request.client else "unknown"
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
    return hmac.new(secret.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def create_session(db, user: User, days: int) -> str:
    token = new_token()
    db.add(Session(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow() + timedelta(days=days)))
    return token


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def optional_user(request: Request, db=Depends(get_db)) -> User | None:
    token = _bearer(request)
    if not token:
        return None
    session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if session is None or session.expires_at < utcnow():
        return None
    user = session.user
    now = utcnow()
    if (now - user.last_seen_at).total_seconds() > 3600:
        user.last_seen_at = now
        db.commit()
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return user


def moderator(user: User = Depends(current_user)) -> User:
    if not user.is_moderator:
        raise HTTPException(status_code=403, detail="Moderators only.")
    return user


def admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admins only.")
    return user
