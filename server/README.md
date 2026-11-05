# Community API

The small server behind the site's community features: sign-in by email link, Interested / Going, event buddies,
the Noticeboard (Wish Wall, achievements, opportunities), the saved arrival checklist, website event suggestions
and the weekly digest. Why each exists: [docs/research/platform-v2.md](../docs/research/platform-v2.md).

The site stays a static site on GitHub Pages. It calls this API from the browser, and only when
`params.communityAPI` is set (the deploy workflow takes it from the repository variable `COMMUNITY_API_URL`).
Without it, the site works exactly as before.

- Python 3.11+, FastAPI, SQLAlchemy. Postgres in production, SQLite for development and tests.
- Interactive API documentation at `/docs` on any running server.
- 17 tests, run on both SQLite and Postgres in CI (`pytest server -q`).

## Run it on your computer

```bash
cd server
python -m venv .venv
. .venv/bin/activate                     # Windows: .venv\Scripts\activate
pip install -e '.[test]'
SITE_URL=http://localhost:1313/ ADMIN_EMAILS=you@utas.edu.au hellotas-api serve --port 8000 --reload
```

In a second terminal, from the repository root, start Hugo pointed at it:

```bash
HUGO_PARAMS_COMMUNITYAPI=http://localhost:8000 hugo server
```

Open http://localhost:1313/account/ and sign in. With the default `EMAIL_BACKEND=console`, emails are printed in
the API's terminal instead of being sent, so copy the sign-in link from there. Data goes into `server/hellotas.db`
(SQLite); delete the file to start again.

## Settings

All settings are environment variables (or a `.env` file read by docker compose). `.env.example` lists them.

| Variable | Default | What it does |
|---|---|---|
| `SITE_URL` | `https://dongyi-guo.github.io/hellotas/` | The site, ending in `/`. Sign-in links point here, and the API reads the events from `happening/index.json` under it. |
| `ALLOWED_ORIGINS` | the site and local Hugo | Origins allowed to call the API from a browser (CORS), comma-separated. Must include the site's origin. |
| `ALLOWED_EMAIL_DOMAINS` | `utas.edu.au` | Who can sign in. `*` allows any address; don't, unless moderators are ready for the public. |
| `ADMIN_EMAILS` | none | Addresses that become admins when they first sign in. Admins appoint moderators on `/moderate/`. |
| `SECRET_KEY` | random per start | Keys the hashes of visitors' IP addresses used for rate limits. Set it, so limits survive restarts. |
| `DATABASE_URL` | `sqlite:///./hellotas.db` | `postgresql://user:password@host/db?sslmode=require` in production. `postgres://` URLs work too. |
| `EMAIL_BACKEND` | `console` | `console` (print), `smtp` or `resend`. |
| `EMAIL_FROM` | | Sender, e.g. `Tasmania Welcome <hello@ictfuturesintas.com>`. Must be on a domain verified with your provider. |
| `RESEND_API_KEY` | | For `EMAIL_BACKEND=resend`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | port 587 | For `EMAIL_BACKEND=smtp` (STARTTLS). |
| `GITHUB_REPO`, `GITHUB_TOKEN` | `dongyi-guo/hellotas`, none | Website suggestions become "Event suggestion" issues there. A fine-grained token for that repository with *Issues: read and write* only. Without it, suggestions wait on `/moderate/`. |
| `CRON_SECRET` | none | Protects `POST /v1/admin/digest/send`. The same value goes in the repository secret `COMMUNITY_CRON_SECRET`. |
| `TRUST_PROXY` | `false` (`true` in the container) | Behind a proxy, use the visitor's address from `X-Forwarded-For` for rate limits. |
| `SESSION_DAYS` | `30` | How long a sign-in lasts. |

## Deploying

Three things have to exist: somewhere to run the container, a Postgres database, and a way to send email. Pick a
region in Australia where you can (Sydney or Melbourne): it is closer to Hobart, and it keeps students' data in
Australia, which UTAS will ask about.

**Recommendation.** Start with option A. It costs nothing at this scale and needs no server maintenance. Move to
option C (a UTAS virtual machine) if the School of ICT is willing to host it: that is the best long-term home,
because the service then outlives any one cohort of student volunteers.

### Option A: Google Cloud Run, Neon and Resend (about $0 a month at this scale)

Cloud Run runs the container only while requests come in (free allowance: 2 million requests a month), Neon
provides Postgres with a free plan that suspends when idle, and Resend sends email (free: 100 a day, 3,000 a
month). Cloud Run needs a Google Cloud billing account, even within the free allowance. Check the current limits
on each provider's pricing page; they change.

1. **Database.** Create a Neon project (choose the region nearest Australia that it offers). Copy the connection
   string; it looks like `postgresql://user:password@ep-xxx.ap-southeast-2.aws.neon.tech/neondb?sslmode=require`.
2. **Email.** Create a Resend account, add and verify your sending domain (it gives you DNS records: SPF and DKIM),
   and create an API key. Until the domain is verified, Resend only sends to your own address.
3. **Deploy** from the repository root with the [gcloud CLI](https://cloud.google.com/sdk/docs/install):

   ```bash
   gcloud run deploy hellotas-api --source server --region australia-southeast1 --allow-unauthenticated \
     --set-env-vars "SITE_URL=https://dongyi-guo.github.io/hellotas/,ALLOWED_ORIGINS=https://dongyi-guo.github.io,ADMIN_EMAILS=you@utas.edu.au,EMAIL_BACKEND=resend,EMAIL_FROM=Tasmania Welcome <hello@your-domain>,GITHUB_REPO=dongyi-guo/hellotas" \
     --set-secrets "DATABASE_URL=hellotas-db:latest,SECRET_KEY=hellotas-secret:latest,RESEND_API_KEY=hellotas-resend:latest,GITHUB_TOKEN=hellotas-github:latest,CRON_SECRET=hellotas-cron:latest"
   ```

   Create each secret first in Secret Manager (`gcloud secrets create hellotas-db --data-file=-`, then paste the
   value and press Ctrl+D), and give the Cloud Run service account the *Secret Manager Secret Accessor* role.
   The command prints the service address, `https://hellotas-api-....run.app`.
4. Check `https://<address>/health` shows `"ok": true` and a non-zero `events_on_site`.
5. Connect the site (below).

The first request after an idle spell takes a few seconds while Cloud Run starts the container.
`--min-instances 1` removes that delay, but is no longer free.

### Option B: one small server with docker compose (about A$10 a month)

Any Linux virtual machine with 1 GB of memory: a VPS from any provider, or a UTAS virtual machine (option C). The
compose file runs Caddy (HTTPS with automatic certificates), the API, Postgres and a daily backup.

1. Point a DNS name at the server's IP address, e.g. an `A` record for `api.ictfuturesintas.com` (upstream issue #70).
2. Install Docker (`curl -fsSL https://get.docker.com | sh`) and open ports 80 and 443.
3. On the server:

   ```bash
   git clone https://github.com/dongyi-guo/hellotas.git
   cd hellotas/server
   cp .env.example .env             # fill it in; leave DATABASE_URL, compose sets it
   cd deploy
   export API_DOMAIN=api.ictfuturesintas.com
   export POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
   echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD" >> ../.env   # keep it: the database needs the same one next time
   docker compose up -d --build
   docker compose logs -f api caddy  # Caddy fetches the certificate within a minute
   ```

4. Check `https://api.ictfuturesintas.com/health`.
5. **Backups**: one compressed dump a day in the `backups` volume, the newest 14 kept. Copy them somewhere else
   regularly (`docker compose cp backup:/backups ./backups`). To restore one:
   `gunzip -c hellotas-YYYYMMDD-HHMM.sql.gz | docker compose exec -T db psql -U hellotas hellotas`.
6. **Updates**: `git pull && docker compose up -d --build`.

Without a domain yet, `API_DOMAIN=localhost` serves HTTPS on the server itself with a local certificate, which is
enough for testing but not for the site.

### Option C: a UTAS virtual machine

Ask the School of ICT (or UTAS IT) for a small Linux VM with a DNS name, then follow option B. Benefits: data stays
on UTAS infrastructure, staff can take it over when students graduate, and UTAS's own mail relay may be usable
for `EMAIL_BACKEND=smtp`.

### Not recommended: Render's free plan

Free Render databases are deleted 30 days after creation (after a 14-day grace period), and free web services stop
after 15 minutes without traffic and take about a minute to wake, which would make sign-in links feel broken. Its
paid plans work fine with the Dockerfile.

## Connect the site

1. In the API's settings, make sure `ALLOWED_ORIGINS` contains the site's origin (`https://dongyi-guo.github.io`,
   or your custom domain) and `SITE_URL` is the site's address.
2. In GitHub: Settings > Secrets and variables > Actions > Variables > `COMMUNITY_API_URL` =
   the API's address without a trailing slash, e.g. `https://api.ictfuturesintas.com`.
3. Re-run the deploy (Actions > Deploy Hugo to GitHub Pages > Run workflow). The account, Noticeboard, buddy
   buttons, digest form and saved checklist appear.
4. Sign in with an address from `ADMIN_EMAILS`, open `/moderate/`, and give your moderators the moderator role
   (they have to sign in once first). Or on the server: `hellotas-api make-admin someone@utas.edu.au`.

## The weekly digest

`.github/workflows/weekly-digest.yml` calls the API every Monday morning (Hobart time). It needs:

- secret `COMMUNITY_CRON_SECRET`, the same value as the API's `CRON_SECRET`;
- the `COMMUNITY_API_URL` variable from above.

Resend's free plan stops at 100 emails a day. Past about 90 subscribers, move to Resend's paid plan or another
provider (Amazon SES, Brevo), or the digest will stop partway. `/moderate/` shows the subscriber count.

## Running it

- **Moderation.** New posts wait on `/moderate/` until a moderator approves them. Aim to clear the queue every day
  or two; reported posts are listed there too, with one-click hiding.
- **Numbers.** `/moderate/` shows sign-ups, active users, buddy requests and how many were accepted, posts and
  digest subscribers. Look at them each semester and drop what isn't used.
- **Data requests.** People download their data and delete their account themselves on `/account/`. Deletion
  removes everything they added, including approved posts.
- **Database changes.** Tables are created on start if missing; existing tables are never altered. The first
  time a column has to change, add [Alembic](https://alembic.sqlalchemy.org/) migrations rather than editing a
  live database by hand.
- **Logs.** Cloud Run: the Logs tab. Compose: `docker compose logs -f api`.

## How it protects people

- Only UTAS addresses can sign in. Sign-in links work once, for 20 minutes, and arrive in the URL fragment (`#`),
  which browsers never send to servers. Links and sessions are stored only as SHA-256 hashes.
- Buddy lists are visible only to signed-in users and never include email addresses; addresses are exchanged
  only when the person asked accepts, by email to both.
- Posts are public only after a moderator approves them; anyone signed in can report one.
- Text is stored as plain text (control and direction-override characters removed) and the site only displays
  it as text, never as HTML.
- Sessions travel in the `Authorization` header, not cookies, so other sites can't make requests on someone's
  behalf; CORS admits only the site.
- Rate limits on sign-in emails, posts, buddy requests, suggestions and digest sign-ups, keyed on a keyed hash
  of the visitor's address; addresses themselves are never stored.
- The digest needs double opt-in and supports one-click unsubscribe (RFC 8058).
