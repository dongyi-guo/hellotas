"""Event suggestions from the website's form.

From a signed-in UTAS user: forwarded to GitHub straight away (an "Event suggestion" issue, which the collector
turns into a pull request). From anyone else: kept for a moderator to forward or reject, so the public form can't
be used to flood the repository.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import Suggestion, User
from ..security import client_key, get_db, optional_user
from .common import clean_text, clean_url, state
from .mod import forward, suggestion_out

router = APIRouter(prefix="/v1", tags=["suggestions"])


class NewSuggestion(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    details: str = Field(default="", max_length=4000)
    note: str = Field(default="", max_length=1000)
    website: str = Field(default="", max_length=200)  # a field people can't see; bots fill it in


@router.post("/suggestions", status_code=201)
def suggest(body: NewSuggestion, request: Request, user: User | None = Depends(optional_user), db=Depends(get_db)):
    app = state(request)
    if body.website:
        return {"status": "pending"}  # quietly drop bot submissions
    app.limiter.hit("suggest", client_key(request, app.settings.secret_key, app.settings.trust_proxy))
    url = clean_url(body.url)
    if not url:
        raise HTTPException(status_code=422, detail="Add the event's link.")
    s = Suggestion(user_id=user.id if user else None, url=url, details=clean_text(body.details, 4000, multiline=True),
                   note=clean_text(body.note, 1000, multiline=True))
    db.add(s)
    db.flush()
    if user is not None:
        forward(request, s, f"{user.public_name} (signed in)")
    db.commit()
    return suggestion_out(s)
