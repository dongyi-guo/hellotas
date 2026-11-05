"""A polite HTTP client.

Rules it keeps, whoever calls it:
  * it says who it is (User-Agent with a link back to this repository);
  * it obeys robots.txt for that User-Agent;
  * it waits between requests to the same site;
  * a challenge page, firewall block or 401/403/429 is reported as Blocked and never retried with a disguise;
  * for links people submit, it refuses addresses on private networks (so a form can't be used to probe them).
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests

from .robots import Robots, product_token

MAX_PAGE_BYTES = 6 * 1024 * 1024
MAX_IMAGE_BYTES = 12 * 1024 * 1024

_CHALLENGE_MARKERS = (
    "cf-chl", "challenges.cloudflare.com", "just a moment...", "attention required!",
    "web application firewall", "access denied", "request unsuccessful. incapsula",
    "please enable cookies", "captcha",
)


class FetchError(Exception):
    """The page could not be fetched (network error, 404, too big, ...)."""


class Blocked(FetchError):
    """The site doesn't want automated visitors here: robots.txt, a challenge page or an access refusal."""


@dataclass
class Page:
    url: str  # final URL after redirects
    status: int
    content_type: str
    body: bytes

    @property
    def text(self) -> str:
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return self.body.decode(enc)
            except UnicodeDecodeError:
                continue
        return self.body.decode("utf-8", "replace")


def is_public_host(host: str) -> bool:
    """True when every address the name resolves to is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
                or addr.is_multicast or addr.is_unspecified):
            return False
    return True


class Fetcher:
    def __init__(self, user_agent: str, delay: float = 1.5, timeout: float = 25.0,
                 public_only: bool = False, session: requests.Session | None = None):
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self.public_only = public_only
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "en-AU,en;q=0.8",
        })
        self.token = product_token(user_agent)
        self._robots: dict[str, tuple[Robots | None, str]] = {}
        self._last: dict[str, float] = {}
        self.requests_made = 0

    # -- robots.txt -------------------------------------------------------------------------------------------
    def _fetch_robots(self, origin: str) -> tuple[int, str]:
        target = urljoin(origin, "/robots.txt")
        for attempt in (1, 2, 3):
            try:
                for _hop in range(5):  # RFC 9309: follow at least five redirects
                    resp = self._raw_get(target, check_robots=False, stream=False)
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                        target = urljoin(target, resp.headers["Location"])
                        continue
                    if resp.status_code >= 500 and attempt < 3:
                        break  # retry below
                    return resp.status_code, (resp.text if resp.status_code == 200 else "")
            except (requests.RequestException, FetchError):
                pass
            time.sleep(2 * attempt)
        return 0, ""

    def _robots_for(self, url: str) -> tuple[Robots | None, str]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            status, body = self._fetch_robots(origin)
            if status == 200 and not _looks_blocked(status, body):
                self._robots[origin] = (Robots(body), "")
            elif status in (401, 403, 429) or _looks_blocked(status, body):
                self._robots[origin] = (None, f"{parts.netloc} refuses automated visitors (HTTP {status} even "
                                              "for robots.txt)")
            elif status == 0 or status >= 500:
                # RFC 9309: an unreachable robots.txt means everything is disallowed until it can be read
                self._robots[origin] = (None, f"{parts.netloc}/robots.txt couldn't be read (network or server "
                                              "error), so the site is left alone this time")
            else:
                self._robots[origin] = (Robots(""), "")  # 404 and other 4xx: no rules
        return self._robots[origin]

    def allowed(self, url: str) -> bool:
        return self.why_not(url) == ""

    def why_not(self, url: str) -> str:
        """'' when the URL may be fetched, otherwise the reason it may not."""
        robots, reason = self._robots_for(url)
        if robots is None:
            return reason
        if not robots.allowed(self.token, url):
            return f"robots.txt asks crawlers not to visit {urlsplit(url).path or '/'}"
        return ""

    # -- requests ---------------------------------------------------------------------------------------------
    def _wait_turn(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < self.delay:
                time.sleep(self.delay - gap)
        self._last[host] = time.monotonic()

    def _check_target(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FetchError(f"Not a web address: {url}")
        if self.public_only and not is_public_host(parts.hostname):
            raise FetchError(f"Refusing to fetch a private or unknown address: {parts.hostname}")

    def _raw_get(self, url: str, check_robots: bool = True, stream: bool = True, accept: str | None = None):
        """One request, no redirects followed (get() follows them so every hop is checked)."""
        self._check_target(url)
        if check_robots:
            reason = self.why_not(url)
            if reason:
                raise Blocked(reason)
        self._wait_turn(urlsplit(url).netloc)
        headers = {"Accept": accept} if accept else {}
        self.requests_made += 1
        return self.session.get(url, headers=headers, timeout=self.timeout, stream=stream, allow_redirects=False)

    def _get_once(self, url: str, accept: str | None) -> requests.Response:
        """A request with retries for network errors and server errors (5xx)."""
        for attempt in (1, 2, 3):
            try:
                resp = self._raw_get(url, accept=accept)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise FetchError(f"{url}: {exc}") from exc
                time.sleep(2 * attempt)
                continue
            if resp.status_code >= 500 and attempt < 3:
                resp.close()
                time.sleep(2 * attempt)
                continue
            return resp
        raise FetchError(f"{url}: no response")  # not reached

    def get(self, url: str, accept: str | None = None, limit: int = MAX_PAGE_BYTES) -> Page:
        current = url
        for _hop in range(8):
            resp = self._get_once(current, accept)
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
                resp.close()
                current = urljoin(current, resp.headers["Location"])
                continue  # the next hop is checked (address and robots.txt) like the first
            try:
                body = _read_limited(resp, limit)
            except requests.RequestException as exc:
                raise FetchError(f"{current}: {exc}") from exc
            status = resp.status_code
            if _looks_blocked(status, body[:20000].decode("utf-8", "ignore")):
                raise Blocked(f"{urlsplit(current).netloc} refused automated access (HTTP {status})")
            if status >= 400:
                raise FetchError(f"{current}: HTTP {status}")
            return Page(current, status, resp.headers.get("Content-Type", ""), body)
        raise FetchError(f"{url}: too many redirects")


def _read_limited(resp: requests.Response, limit: int) -> bytes:
    chunks, size = [], 0
    for chunk in resp.iter_content(64 * 1024):
        size += len(chunk)
        if size > limit:
            resp.close()
            raise FetchError(f"{resp.url}: larger than {limit // (1024 * 1024)} MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _looks_blocked(status: int, text: str) -> bool:
    if status in (401, 403, 429):
        return True
    if status in (503, 202, 200) and text:
        low = text[:6000].lower()
        if status != 200:
            return any(m in low for m in _CHALLENGE_MARKERS)
        # A 200 page that is only a challenge (no real content) also counts
        return ("challenges.cloudflare.com" in low and "<title>just a moment" in low) or (
            "web application firewall has blocked" in low)
    return False
