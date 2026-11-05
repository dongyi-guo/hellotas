"""The FastAPI application. `create_app()` builds it from environment variables (or from what tests pass in)."""

from __future__ import annotations

import requests
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text as sql

from . import __version__
from .config import Settings, from_env
from .db import Base, make_engine, make_sessionmaker
from .feed import EventFeed
from .limits import Limiter
from .mail import Mailer
from .routes import auth, digest, events, me, mod, posts, suggest


def create_app(settings: Settings | None = None, feed: EventFeed | None = None, mailer: Mailer | None = None,
               http: requests.Session | None = None) -> FastAPI:
    settings = settings or from_env()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)  # creates missing tables; existing ones are left alone

    app = FastAPI(title="Tasmania Welcome community API", version=__version__,
                  description="Accounts, event buddies, walls, opportunities, checklist and the weekly digest. "
                              "See server/README.md.", redoc_url=None)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.feed = feed or EventFeed(settings.feed_url, settings.feed_refresh_seconds)
    app.state.mailer = mailer or Mailer(settings)
    app.state.limiter = Limiter()
    app.state.http = http or requests.Session()

    # Sessions travel in the Authorization header, not cookies, so no credentials mode and no CSRF exposure
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], max_age=600)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/v1/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def readable_validation(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        message = first.get("msg", "Invalid request")
        return JSONResponse(status_code=422, content={"detail": f"{field}: {message}" if field else message})

    for router in (auth.router, me.router, events.router, posts.router, mod.router, digest.router, suggest.router):
        app.include_router(router)

    @app.get("/health", tags=["health"])
    def health():
        with engine.connect() as conn:
            conn.execute(sql("SELECT 1"))
        return {"ok": True, "version": __version__, "events_on_site": len(app.state.feed.events())}

    @app.get("/v1/config", tags=["health"])
    def public_config():
        """What the site needs to know: who may sign in."""
        return {"email_domains": settings.allowed_email_domains, "version": __version__}

    return app
