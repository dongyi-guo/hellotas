import socket

import pytest

from hellotas_collector import fetch as fetch_module
from hellotas_collector.fetch import Blocked, Fetcher, FetchError
from hellotas_collector.robots import Robots, product_token

MEETUP_LIKE = """
User-agent: *
Disallow: /files/

User-agent: *
Disallow: */events/rss/*
Disallow: /*?keywords=*
Disallow: /api/
Allow: /api/public$
"""


def test_wildcards_and_anchors():
    r = Robots(MEETUP_LIKE)
    assert r.allowed("hellotas-collector", "https://www.meetup.com/sectalks-hobart/events/317249458/")
    assert not r.allowed("hellotas-collector", "https://www.meetup.com/g/events/rss/feed")
    assert not r.allowed("hellotas-collector", "https://www.meetup.com/find/?keywords=python")
    assert not r.allowed("hellotas-collector", "https://www.meetup.com/files/x")  # from the first * group
    assert r.allowed("hellotas-collector", "https://www.meetup.com/api/public")  # longer Allow wins
    assert not r.allowed("hellotas-collector", "https://www.meetup.com/api/public/more")  # $ anchors the Allow


def test_named_group_beats_star_and_allow_wins_ties():
    r = Robots("User-agent: *\nDisallow: /\n\nUser-agent: hellotas-collector\nDisallow: /private\nAllow: /private\n")
    assert r.allowed("hellotas-collector", "https://x.org/anything")
    assert r.allowed("hellotas-collector", "https://x.org/private")  # same length: Allow wins
    assert not r.allowed("otherbot", "https://x.org/anything")


def test_gdg_api_is_off_limits():
    r = Robots("User-agent: *\nDisallow: /api/\nDisallow: /accounts/\n")
    assert not r.allowed("hellotas-collector", "https://gdg.community.dev/api/event/133070/")
    assert r.allowed("hellotas-collector", "https://gdg.community.dev/events/details/google-gdg-hobart-presents-x/")


def test_product_token():
    assert product_token("hellotas-collector/1.0 (+https://github.com/dongyi-guo/hellotas)") == "hellotas-collector"


class FakeResponse:
    def __init__(self, url, status=200, text="", headers=None):
        self.url = url
        self.status_code = status
        self.text = text
        self.headers = headers or {}
        self._body = text.encode()

    def iter_content(self, size):
        yield self._body

    def close(self):
        pass


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return self.routes.get(url) or FakeResponse(url, 404, "")


def _fetcher(routes, **kwargs):
    f = Fetcher("hellotas-collector/1.0 (+test)", delay=0, session=FakeSession(routes), **kwargs)
    return f


def test_challenge_page_is_blocked_not_retried_in_disguise():
    routes = {
        "https://www.utas.edu.au/robots.txt": FakeResponse(
            "https://www.utas.edu.au/robots.txt", 403, "<title>Just a moment...</title> challenges.cloudflare.com"),
    }
    f = _fetcher(routes)
    with pytest.raises(Blocked, match="refuses automated visitors"):
        f.get("https://www.utas.edu.au/events")
    # Only robots.txt was asked for, once per attempt, and always with the honest user agent
    assert all(c.endswith("/robots.txt") for c in f.session.calls)
    assert f.session.headers["User-Agent"].startswith("hellotas-collector/")


def test_robots_disallow_is_respected():
    routes = {
        "https://gdg.community.dev/robots.txt": FakeResponse("https://gdg.community.dev/robots.txt", 200,
                                                             "User-agent: *\nDisallow: /api/\n"),
    }
    f = _fetcher(routes)
    with pytest.raises(Blocked, match="asks crawlers not to visit"):
        f.get("https://gdg.community.dev/api/event_slim/for_chapter/1436/")
    assert "https://gdg.community.dev/api/event_slim/for_chapter/1436/" not in f.session.calls


def test_redirect_to_private_address_is_refused(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        ip = "10.0.0.5" if host == "intranet.local" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(fetch_module.socket, "getaddrinfo", fake_getaddrinfo)
    routes = {
        "https://example.org/robots.txt": FakeResponse("https://example.org/robots.txt", 404),
        "https://example.org/event": FakeResponse("https://example.org/event", 302, "",
                                                  {"Location": "http://intranet.local/admin"}),
    }
    f = _fetcher(routes, public_only=True)
    with pytest.raises(FetchError, match="private"):
        f.get("https://example.org/event")
    assert "http://intranet.local/admin" not in f.session.calls


def test_unreachable_robots_means_leave_site_alone(monkeypatch):
    monkeypatch.setattr(fetch_module.time, "sleep", lambda s: None)
    routes = {"https://flaky.org/robots.txt": FakeResponse("https://flaky.org/robots.txt", 503, "")}
    f = _fetcher(routes)
    with pytest.raises(Blocked, match="couldn't be read"):
        f.get("https://flaky.org/events")
