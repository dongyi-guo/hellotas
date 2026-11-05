# Next steps

What is left after the automation and community work, as checklists. (These were meant to be GitHub issues, but
Issues are switched off in this fork: Settings > General > Features > Issues turns them on.)

## 1. Switch on the automation

Settings > Actions > General, and Settings > Secrets and variables > Actions. Details: [DEPLOYMENT.md](DEPLOYMENT.md).

- [ ] Workflow permissions: *Read and write*, and *Allow GitHub Actions to create and approve pull requests*
- [ ] Turn on Issues (Settings > General > Features), so the **Suggest an event** form works
- [ ] Secret `ANTHROPIC_API_KEY`, for relevance judging and the Chinese and Nepali text
- [ ] Run Actions > Collect events > Run workflow once, and review the pull request it opens
- [ ] After a few weeks of pull requests you would have merged as they are: variable `COLLECTOR_PUBLISH` = `true`
- [ ] Optional: create the Discord server (the header icon waits for a URL in `data/channels.yaml`), then add a
      channel webhook as the secret `DISCORD_WEBHOOK_URL`

## 2. Deploy the community API

Full guide: [server/README.md](../server/README.md#deploying).

- [ ] Choose hosting: Cloud Run + Neon + Resend (recommended to start, about $0), one small server with docker
      compose, or a UTAS virtual machine (best long-term home: ask the School of ICT)
- [ ] Verify a sending domain with the email provider (SPF and DKIM records)
- [ ] Create a fine-grained GitHub token (this repository, *Issues: read and write*) for website suggestions
- [ ] Deploy, check `/health`, set the variable `COMMUNITY_API_URL`, re-run the site deploy
- [ ] Sign in with an `ADMIN_EMAILS` address, appoint at least two moderators on `/moderate/`
- [ ] Set `CRON_SECRET` on the API and the same value as the secret `COMMUNITY_CRON_SECRET`, for the weekly digest
- [ ] Decide who clears the moderation queue, and how often (every day or two is the aim)

## 3. Ask organisers and UTAS for permission or feeds

The collector only reads pages that robots.txt allows, but a short email is the courteous and lasting step, and
for UTAS and Careerify it is the only way in.

- [ ] GDG Hobart, TasICT, ACS Tasmania, AISA Hobart, SecTalks Hobart: "may our student site list your events, linking
      back to your page?" Most organisers welcome the promotion.
- [ ] UTAS Events: an iCalendar or JSON feed of School of ICT events (utas.edu.au blocks automated visitors)
- [ ] Careerify (Department for Education, Children and Young People): an allowance for the collector, or a feed
- [ ] LinkedIn: no automated access is allowed. Ask organisers who announce on LinkedIn to include a registration link

## 4. Decisions for the team

- [ ] **Header space.** The desktop menu is exactly as wide as its space, so the Noticeboard and Sign in links are in
      the ☰ menu, the footer and a homepage section instead. To give them a header button, the menu needs about
      100px: shorter labels, or dropping *Home* (the logo already links home).
- [ ] **Who can sign in.** UTAS addresses only, so every poster is a real student or staff member. New students may
      not have their UTAS address before they arrive; opening sign-in wider needs more moderation.
- [ ] **Domain** (upstream issue 70): `www.` for the site and `api.` for the API on the chosen domain.
- [ ] **Measure.** At the end of each semester, read the numbers on `/moderate/` (sign-ups, buddy requests and how
      many were accepted, posts, digest subscribers) and drop what isn't used.

## Known limits

- The AI step was tested against a stand-in for the Anthropic API (request format, caching, fallbacks), not against
  Claude itself, because no key was available. The first real run's report shows the actual results and cost.
- The weekly digest stops at the email provider's daily limit (100 a day on Resend's free plan).
- Rate limits are kept in memory, so with several API instances each counts on its own.
- Database tables are created when missing but never altered; the first schema change needs migrations (Alembic).
