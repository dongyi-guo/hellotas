"""robots.txt rules as RFC 9309 defines them.

Python's urllib.robotparser predates the RFC: it ignores the * and $ wildcards and lets the first matching rule
win. Under RFC 9309 the most specific (longest) matching rule wins and Allow wins a tie, and every group naming the
same user agent counts (Meetup's file repeats `User-agent: *` many times).
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit


def _compile(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile("^" + rx + ("$" if anchored else ""))


class Robots:
    def __init__(self, text: str):
        self.groups: list[tuple[set[str], list[tuple[bool, str, re.Pattern]]]] = []
        agents: set[str] = set()
        rules: list[tuple[bool, str, re.Pattern]] = []
        in_rules = False
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:  # a user-agent line after rules starts a new group
                    self.groups.append((agents, rules))
                    agents, rules, in_rules = set(), [], False
                agents.add(value.lower())
            elif key in ("allow", "disallow"):
                in_rules = True
                if value:  # an empty Disallow means "nothing is disallowed"
                    value = unquote(value)
                    rules.append((key == "allow", value, _compile(value)))
        if agents:
            self.groups.append((agents, rules))

    def _rules_for(self, token: str) -> list[tuple[bool, str, re.Pattern]]:
        token = token.lower()
        named = [r for agents, rules in self.groups if token in agents for r in rules]
        if any(token in agents for agents, _ in self.groups):
            return named
        return [r for agents, rules in self.groups if "*" in agents for r in rules]

    def allowed(self, token: str, url: str) -> bool:
        parts = urlsplit(url)
        path = unquote(parts.path or "/") + (("?" + unquote(parts.query)) if parts.query else "")
        if path == "/robots.txt":
            return True
        best_len, best_allow = -1, True
        for allow, pattern, rx in self._rules_for(token):
            if rx.match(path):
                length = len(pattern)
                if length > best_len or (length == best_len and allow):
                    best_len, best_allow = length, allow
        return best_allow


def product_token(user_agent: str) -> str:
    """'hellotas-collector/1.0 (+https://...)' -> 'hellotas-collector'"""
    return re.split(r"[/\s]", user_agent.strip(), maxsplit=1)[0]
