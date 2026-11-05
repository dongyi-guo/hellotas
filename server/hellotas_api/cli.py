"""Command line: `hellotas-api serve | send-digest | make-admin`."""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import select


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hellotas-api")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("serve", help="run the API (reads settings from environment variables)")
    p.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    p.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    p = sub.add_parser("send-digest", help="send the weekly digest now")
    p.add_argument("--base-url", default=os.environ.get("API_URL", "http://localhost:8000"),
                   help="the API's public address, for unsubscribe links")
    p = sub.add_parser("make-admin", help="give an address the admin role (creating the account if needed)")
    p.add_argument("email")
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn
        uvicorn.run("hellotas_api.app:create_app", factory=True, host=args.host, port=args.port,
                    reload=args.reload, proxy_headers=True, forwarded_allow_ips="*")
        return 0

    from .app import create_app
    from .models import User
    from .routes.digest import send_all
    from .security import default_name
    app = create_app()
    db = app.state.sessionmaker()
    try:
        if args.command == "send-digest":
            print(send_all(app.state, db, args.base_url))
        elif args.command == "make-admin":
            email = args.email.strip().lower()
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, display_name=default_name(email))
                db.add(user)
            user.role = "admin"
            db.commit()
            print(f"{email} is now an admin.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
