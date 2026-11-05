"""Forwarding website suggestions to GitHub as "Event suggestion" issues, the same format as the issue form
(.github/ISSUE_TEMPLATE/suggest-event.yml), so .github/workflows/event-suggestion.yml handles both alike."""

from __future__ import annotations

import requests


def issue_body(url: str, details: str, note: str, who: str) -> str:
    def answer(text: str) -> str:
        return text.strip() or "_No response_"
    return (f"### Event link\n\n{answer(url)}\n\n### Event details\n\n{answer(details)}\n\n"
            f"### Why it's useful\n\n{answer(note)}\n\n---\n_Sent from the website by {who}._\n")


def create_issue(repo: str, token: str, url: str, details: str, note: str, who: str,
                 session: requests.Session | None = None) -> str:
    """Returns the new issue's web address. Raises requests.HTTPError on failure."""
    http = session or requests.Session()
    title = "Event suggestion: " + (url[:80] if url else "from the website")
    resp = http.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "hellotas-api/1.0"},
        json={"title": title, "body": issue_body(url, details, note, who), "labels": ["event-suggestion"]},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["html_url"]
