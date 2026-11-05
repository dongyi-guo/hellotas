from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hellotas_api.app import create_app
from hellotas_api.config import Settings
from hellotas_api.feed import EventFeed
from hellotas_api.mail import Mailer


def iso(days: float) -> str:
    return (datetime.now(timezone(timedelta(hours=11))) + timedelta(days=days)).replace(microsecond=0).isoformat()


EVENTS = [
    {"id": "gdg-hobart-devfest-2026", "title": "GDG Hobart DevFest 2026", "start": iso(3), "end": iso(3.1),
     "format": "in_person", "location": "Centenary Building", "topics": ["ai", "development"], "host": "GDG Hobart",
     "cost": "Free", "summary": "Gemini in Android Studio.", "url": "https://gdg.community.dev/x/",
     "page": "https://site.example/happening/#event-gdg-hobart-devfest-2026", "all_day": False, "date_tbc": False},
    {"id": "acs-get-a-job-in-data", "title": "How to Get a Job in Data", "start": iso(10), "end": iso(10.05),
     "format": "online", "location": "", "topics": ["careers", "data"], "host": "ACS", "cost": "Free for members",
     "summary": "What employers want.", "url": "https://acs.example/data", "page": "https://site.example/happening/#event-acs",
     "all_day": False, "date_tbc": False},
    {"id": "old-meetup", "title": "An event that is over", "start": iso(-5), "end": iso(-4.9), "format": "in_person",
     "location": "Hobart", "topics": ["community"], "host": "SecTalks", "cost": "", "summary": "",
     "url": "https://x.example", "page": "", "all_day": False, "date_tbc": False},
    {"id": "far-future", "title": "Too far away for the digest", "start": iso(60), "end": iso(60.1), "format": "online",
     "location": "", "topics": ["cyber"], "host": "AISA", "cost": "", "summary": "", "url": "https://x.example/f",
     "page": "", "all_day": False, "date_tbc": False},
]


class FakeGitHub:
    def __init__(self):
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})

        class R:
            status_code = 201

            def raise_for_status(self):
                pass

            def json(self):
                return {"html_url": "https://github.com/dongyi-guo/hellotas/issues/99"}
        return R()


@pytest.fixture
def feed_file(tmp_path: Path) -> Path:
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"events": EVENTS}), encoding="utf-8")
    return path


@pytest.fixture
def app(tmp_path, feed_file):
    # SQLite by default; set TEST_DATABASE_URL=postgresql+psycopg://... to run the same tests on Postgres
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    if not url.startswith("sqlite"):
        from sqlalchemy import create_engine

        import hellotas_api.models  # noqa: F401  (registers the tables)
        from hellotas_api.db import Base
        engine = create_engine(url)
        Base.metadata.drop_all(engine)
        engine.dispose()
    settings = Settings(database_url=url, site_url="https://site.example/",
                        allowed_email_domains=["utas.edu.au"], admin_emails=["admin@utas.edu.au"],
                        secret_key="test-secret", cron_secret="cron-secret", github_token="gh-token",
                        allowed_origins=["https://site.example"])
    feed = EventFeed(lambda lang: str(feed_file), refresh_seconds=0)
    return create_app(settings, feed=feed, mailer=Mailer(settings), http=FakeGitHub())


@pytest.fixture
def client(app):
    return TestClient(app)


def last_email(app, to: str):
    for msg in reversed(app.state.mailer.outbox):
        if msg.to == to:
            return msg
    raise AssertionError(f"no email to {to}")


def sign_in(client, app, email: str) -> dict:
    """Request a link, read it from the outbox, verify it. Returns Authorization headers."""
    assert client.post("/v1/auth/request", json={"email": email}).status_code == 202
    token = re.search(r"#signin=([\w-]+)", last_email(app, email).text).group(1)
    resp = client.post("/v1/auth/verify", json={"token": token})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}
