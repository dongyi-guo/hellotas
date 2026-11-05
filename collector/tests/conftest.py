from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hellotas_collector.fetch import Blocked, FetchError, Page

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]
HOBART = ZoneInfo("Australia/Hobart")
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=HOBART)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Answers from a dict of url -> text (or an exception to raise). Records what was asked for."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.asked: list[str] = []
        self.user_agent = "test"

    def get(self, url, accept=None, limit=None):
        self.asked.append(url)
        if url not in self.pages:
            raise FetchError(f"{url}: HTTP 404")
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        body = value if isinstance(value, bytes) else value.encode("utf-8")
        return Page(url=url, status=200, content_type="text/html", body=body)

    def allowed(self, url):
        return not isinstance(self.pages.get(url), Blocked)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A minimal copy of the site: hugo.toml, the real collector config, one upcoming and one archived event."""
    (tmp_path / "hugo.toml").write_text('baseURL = "https://example.org/"\n')
    (tmp_path / "collector").mkdir()
    shutil.copy(REPO / "collector" / "sources.yaml", tmp_path / "collector" / "sources.yaml")
    happening = tmp_path / "data" / "happening"
    happening.mkdir(parents=True)
    shutil.copy(REPO / "data" / "happening" / "gdg-hobart-devfest-2026.yaml", happening)
    shutil.copy(REPO / "data" / "happening" / "acs-get-a-job-in-data.yaml", happening)
    archive = tmp_path / "data" / "events" / "2026"
    archive.mkdir(parents=True)
    shutil.copy(REPO / "data" / "events" / "2026" / "gdg-hobart-ai-agents.yaml", archive)
    (tmp_path / "static" / "images" / "happening").mkdir(parents=True)
    return tmp_path
