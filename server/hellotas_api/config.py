"""Settings, all from environment variables (see server/README.md and .env.example)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Settings:
    database_url: str = "sqlite:///./hellotas.db"
    # The public site (ends with /). Links in emails point here; the events feed is read from here.
    site_url: str = "https://dongyi-guo.github.io/hellotas/"
    # Where browsers may call the API from (the site's origin, plus local Hugo for development)
    allowed_origins: list[str] = field(default_factory=lambda: [
        "https://dongyi-guo.github.io", "http://localhost:1313", "http://127.0.0.1:1313"])
    # Who may sign in. "*" allows any address (not recommended for a public site).
    allowed_email_domains: list[str] = field(default_factory=lambda: ["utas.edu.au"])
    # These addresses become admins when they first sign in
    admin_emails: list[str] = field(default_factory=list)
    secret_key: str = ""
    # Email: "console" (print to the log, for development), "smtp" or "resend"
    email_backend: str = "console"
    email_from: str = "Tasmania Welcome <no-reply@example.org>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    resend_api_key: str = ""
    # Website suggestions become issues in this repository (needs a token with Issues: write)
    github_repo: str = "dongyi-guo/hellotas"
    github_token: str = ""
    # Protects POST /v1/admin/digest/send (called weekly by .github/workflows/weekly-digest.yml)
    cron_secret: str = ""
    # Behind a proxy (Caddy, Cloud Run, Render, Fly): trust X-Forwarded-For for rate limiting
    trust_proxy: bool = False
    session_days: int = 30
    login_link_minutes: int = 20
    feed_refresh_seconds: int = 600

    @property
    def any_domain(self) -> bool:
        return "*" in self.allowed_email_domains

    def feed_url(self, lang: str = "en") -> str:
        prefix = "" if lang == "en" else f"{lang}/"
        return f"{self.site_url}{prefix}happening/index.json"


def from_env() -> Settings:
    env = os.environ.get
    s = Settings()
    s.database_url = env("DATABASE_URL", s.database_url)
    if s.database_url.startswith("postgres://"):  # Heroku-style URLs (Render, Neon) -> SQLAlchemy + psycopg 3
        s.database_url = "postgresql+psycopg://" + s.database_url[len("postgres://"):]
    elif s.database_url.startswith("postgresql://"):
        s.database_url = "postgresql+psycopg://" + s.database_url[len("postgresql://"):]
    site = env("SITE_URL", s.site_url)
    s.site_url = site if site.endswith("/") else site + "/"
    if env("ALLOWED_ORIGINS"):
        s.allowed_origins = _list(env("ALLOWED_ORIGINS"))
    if env("ALLOWED_EMAIL_DOMAINS"):
        s.allowed_email_domains = [d.lower() for d in _list(env("ALLOWED_EMAIL_DOMAINS"))]
    s.admin_emails = [e.lower() for e in _list(env("ADMIN_EMAILS", ""))]
    s.secret_key = env("SECRET_KEY", "") or secrets.token_hex(32)
    s.email_backend = env("EMAIL_BACKEND", s.email_backend)
    s.email_from = env("EMAIL_FROM", s.email_from)
    s.smtp_host = env("SMTP_HOST", "")
    s.smtp_port = int(env("SMTP_PORT", "587"))
    s.smtp_user = env("SMTP_USER", "")
    s.smtp_password = env("SMTP_PASSWORD", "")
    s.resend_api_key = env("RESEND_API_KEY", "")
    s.github_repo = env("GITHUB_REPO", s.github_repo)
    s.github_token = env("GITHUB_TOKEN", "")
    s.cron_secret = env("CRON_SECRET", "")
    s.trust_proxy = env("TRUST_PROXY", "false").lower() in ("1", "true", "yes")
    s.session_days = int(env("SESSION_DAYS", "30"))
    return s
