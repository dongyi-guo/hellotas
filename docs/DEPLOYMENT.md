# Deploying Tasmania Welcome

The platform has three parts. Each works without the next one, so they can be switched on one at a time.

| Part | What it is | Where it runs | Cost |
|---|---|---|---|
| The site | Hugo, static pages, calendar and JSON feeds | GitHub Pages (`hugo.yml`) | free |
| The event collector | finds events, opens pull requests, answers suggestions | GitHub Actions (`collector/`) | free; AI optional, a few dollars a month |
| The community API | accounts, buddies, Noticeboard, checklist sync, digest | a container you host (`server/`) | from $0 (Cloud Run + Neon + Resend) |

## 1. The site

Already set up: every push to `main` builds the site and publishes it to the `gh-pages` branch. In the repository's
Settings > Pages, the source must be *Deploy from a branch*, `gh-pages`, `/ (root)`.

**Custom domain** (upstream issue #70): add a `static/CNAME` file containing the domain (for example
`www.ictfuturesintas.com`), point a `CNAME` DNS record for `www` at `<owner>.github.io`, set the domain in
Settings > Pages, tick *Enforce HTTPS*, and change `baseURL` in `hugo.toml` and the `--baseURL` in `hugo.yml` to the
new address.

New feeds the site now publishes (each also under `/zh/` and `/ne/`):

| Address | What |
|---|---|
| `/happening/index.ics` | every upcoming event, for calendar subscriptions (`webcal://`) |
| `/happening/calendar/<topic>/index.ics` | one topic: cyber, ai, careers, data, development, community, ux |
| `/happening/index.json` | the same events as JSON (read by the API and the Discord announcer) |

## 2. The event collector

Full guide: [collector/README.md](../collector/README.md).

1. Settings > Actions > General > Workflow permissions: *Read and write permissions*, and tick *Allow GitHub
   Actions to create and approve pull requests*.
2. Optional but recommended: secret `ANTHROPIC_API_KEY`, so the AI judges relevance and writes the Chinese and
   Nepali text.
3. Actions > Collect events > Run workflow, once, to see the first pull request.
4. After a few weeks of good pull requests, set the variable `COLLECTOR_PUBLISH` to `true` to publish without review.

Suggestions come in through the **Suggest an event** issue form, and through the website once the API is running.

## 3. The community API

Full guide, with three hosting options: [server/README.md](../server/README.md#deploying). In short:

1. Host the container (option A: Cloud Run + Neon + Resend; option B: any small server with
   `server/deploy/docker-compose.yml`; option C: a UTAS virtual machine with the same compose file).
2. Set the repository variable `COMMUNITY_API_URL` to its address and re-run the site deploy.
3. Sign in with an `ADMIN_EMAILS` address and appoint moderators on `/moderate/`.

## Every setting in one place

Settings > Secrets and variables > Actions.

| Name | Kind | Used by | Needed? |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | secret | collector | recommended (otherwise keyword rules, English only) |
| `COLLECTOR_MODEL` | variable | collector | no (default `claude-opus-5-5`) |
| `COLLECTOR_PUBLISH` | variable | collector | no (`true` publishes without a pull request) |
| `DISCORD_WEBHOOK_URL` | secret | site deploy | no (announces new events on Discord) |
| `COMMUNITY_API_URL` | variable | site deploy, weekly digest | only with the API |
| `COMMUNITY_CRON_SECRET` | secret | weekly digest | only with the API (same value as the API's `CRON_SECRET`) |

The API's own settings (database, email, `GITHUB_TOKEN` for website suggestions, ...) live where it is hosted;
see `server/.env.example`.

## What still needs a person

These couldn't be done from the development session that built this, and need someone with the accounts:

- **Hosting the API.** The development container is temporary, so the API was run and tested there (including the
  full `docker compose` stack with HTTPS, Postgres and backups) but not left running anywhere. Someone has to
  create the Cloud Run / Neon / Resend accounts (or a server) and follow `server/README.md`.
- **The AI step.** No Anthropic key was available, so the collector's AI path was tested against a stand-in for
  the API (request format, caching, fallbacks), not against Claude itself. The first real run's report shows the
  actual cost and results.
- **UTAS and Careerify.** utas.edu.au answers every automated request with a Cloudflare challenge, and Careerify's
  firewall refuses cloud networks. Both were left alone. Ask UTAS Events and Careerify for a feed, or rely on
  suggestions.
- **Asking organisers.** GDG Hobart, TasICT, ACS Tasmania, AISA Hobart and SecTalks allow the pages the collector
  reads, but a short email asking for their blessing (or a feed) is the courteous and durable step.
