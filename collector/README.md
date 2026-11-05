# Event collector

Finds upcoming ICT events for the Happening page and writes them into `data/happening/`, in the same format as
the hand-written entries. It replaces the manual sessions where someone browsed each organiser's site and copied
the details across.

It runs by itself every morning (GitHub Actions), and whenever someone suggests an event with the
**Suggest an event** issue form or on the website.

```
 sources.yaml ──► read each source ──► drop: past, too far ahead, already listed, rejected before
                                         │
                                         ▼
                         judge relevance (AI, or keyword rules)
                                         │  60/100 or more
                                         ▼
          write the entry in English, Chinese and Nepali (AI; English only with rules)
                                         │
                                         ▼
     data/happening/<slug>.yaml + cover picture + ledger line ──► pull request (or straight to the site)
```

## What it reads

| Source | How | Notes |
|---|---|---|
| GDG Hobart | event pages' schema.org data | `gdg.community.dev/api/` is disallowed in robots.txt, so it reads the public pages instead |
| ACS | the JSON list behind the ACS events page, then each event page for prices | online events from anywhere, in-person ones only in Tasmania; no short courses, AGMs or members-only events |
| AISA (Hobart and Online branches) | branch pages and event pages (plain HTML) | |
| SecTalks Hobart | Meetup event pages' schema.org data | Meetup keeps its event links in page data, which the collector reads |
| TasICT | event pages, then the Humanitix registration page they link to | pages without event data need the AI to read them |
| Careerify (Tasmanian Government) | iCalendar feed | its firewall refuses some cloud networks; the run summary says when |
| Eventbrite (Hobart, science and tech) | listing page | **off**: mostly children's and library events, and Eventbrite's terms restrict automated access |
| UTAS events | | **off**: utas.edu.au answers every automated request with a Cloudflare challenge |

All sources were checked in November 2026. Every page the collector opens is allowed by that site's robots.txt
for its user agent (`hellotas-collector/1.0 (+https://github.com/dongyi-guo/hellotas)`), and it waits 1.5 seconds
between requests to the same site. When a site blocks it, it reports that and moves on; it never disguises
itself or works around a block.

**LinkedIn** (upstream issue #62) forbids automated access in its terms and robots.txt, and has gone to court
over it (hiQ Labs v. LinkedIn ended in 2022 with a permanent injunction against the scraper). So the collector
never opens LinkedIn links. Instead:

- most LinkedIn event posts link to a Humanitix, Eventbrite or Meetup page: suggest that link and it is read
  automatically;
- otherwise paste the post's text into the suggestion form's *Event details* field, and the AI reads that;
- for a lasting feed, ask the organisers (GDG Hobart, TasICT, ACS Tasmania, AISA Hobart, SecTalks) to add the
  team's address to their event announcements, or ask UTAS for a feed of School of ICT events.

## How it decides

**Duplicates** are caught three ways: the same link as any upcoming *or archived* event (including the links under
`references` in `data/events/`), the same day with a similar title (so GDG Hobart's Bevy page and its Meetup copy
count as one), and `ledger.yaml`, which lists every event the collector has ever proposed. If a proposed event's
file is gone, someone removed it on purpose and it is not proposed again.

**Relevance** is a score from 0 to 100; 60 or more is added (`min_relevance` in `sources.yaml`).

- With the AI, Claude scores each event against a written rubric (made for students or early-career ICT people;
  in Tasmania or online; not for children, executives or paying course customers) and gives a one-line reason.
- Without it, keyword rules score the title and short description: the source's trust level, ICT topics, signs it
  is meant for students, location (Tasmania or online, not in person interstate), and signs it isn't for students
  (AGMs, short courses, children, executive breakfasts). The rules were tuned against the events the team picked
  by hand from the same sources, and they match those picks.

Suggestions from people are always proposed (the reviewer sees the score).

**Writing**: with the AI, Claude writes the title, a summary of up to 45 words, the location and the cost in
English, Simplified Chinese and Nepali, following the house style (Australian English, plain tone, no em dashes)
and copying the tone of six hand-written entries it is shown as examples. Without it, the rules take the
organiser's opening sentences in English only; the Chinese and Nepali pages show English for those events, which
is how the templates already fall back.

The collector never overwrites what people wrote. The only thing it changes in an existing file is `start` and
`end`, and only in files it created (they have a `source:` line), when the organiser changes the date.

## Setting it up on GitHub

1. **Allow pull requests from Actions**: Settings > Actions > General > Workflow permissions > tick *Allow GitHub
   Actions to create and approve pull requests*.
2. **Optional, recommended: the AI.** Settings > Secrets and variables > Actions > New repository secret:
   `ANTHROPIC_API_KEY` (from console.anthropic.com). Without it, the keyword rules are used.
3. **Optional: model.** Variable `COLLECTOR_MODEL`. The default is `claude-opus-5-5` (US$4 / US$20 per million
   input / output tokens). Estimated from the prompt sizes: about US$0.07 for each new event it judges and writes
   up, about US$0.01 to US$0.02 for each event it only judges, and nothing for events it has seen before, because
   answers are cached. At five to ten new events a week that is a few dollars a month; the run report shows the
   real figure. `claude-haiku-5-5` (US$0.10 / US$0.50) costs about a fortieth as much, at some cost to the
   translations, which matters most for Nepali.
4. **Optional: publish without review.** Variable `COLLECTOR_PUBLISH` = `true`. Recommendation: leave it off for
   the first few weeks, check that the pull requests contain what you would have picked, then switch it on.
5. **Optional: Discord.** Secret `DISCORD_WEBHOOK_URL` (Discord: Server settings > Integrations > Webhooks). After
   each deploy, events that are new on the site are posted to that channel.

Then run it once by hand: Actions > Collect events > Run workflow.

## Reviewing what it proposes

The collector keeps one pull request open, **New events from the collector**, and adds to it each day.

- Merge it to publish everything in it.
- Delete a file in the pull request to drop that event; its ledger line keeps it from coming back.
- Edit any text in the branch; the collector won't touch it again (apart from `start` and `end`).
- Close the pull request to reject all of it: `collector-pr-closed.yml` copies its ledger lines to `main`.
- To let a rejected event back in, delete its line from `ledger.yaml`.
- To block a source or organiser for good, add a link or a pattern to `ignore.yaml`.

Pull requests opened by Actions don't start other workflows (a GitHub rule), so the Tests workflow doesn't run on
them automatically; run it from the Actions tab if you want it.

## Running it on your computer

```bash
cd collector
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e '.[test]'
cd ..
hellotas-collect run --dry-run          # read everything, write nothing, print the report
hellotas-collect run                    # write new events into data/happening/
hellotas-collect run --sources acs,aisa # only some sources
hellotas-collect suggest https://events.humanitix.com/some-event
hellotas-collect sources --check        # can each source be reached?
pytest collector -q                     # tests (no network needed)
```

Set `ANTHROPIC_API_KEY` in your shell to use the AI, or pass `--no-ai` to force the rules.

## Adding a source

Add an entry to `sources.yaml`. Most event platforms (Humanitix, Eventbrite, Meetup, GDG) publish schema.org
event data, so the `jsonld` kind usually works with just a listing page and a `follow` pattern for the event
links:

```yaml
  - id: hobart-python
    name: "Hobart Python meetup"
    kind: jsonld
    trust: high
    listing: "https://www.meetup.com/some-group/events/"
    follow: '^https://www\.meetup\.com/some-group/events/\d+/?$'
    defaults: { host: "Hobart Python", topics: [development, community], region: "TAS", type: "meetup" }
```

Check its robots.txt first (the collector will refuse otherwise), then run
`hellotas-collect run --dry-run --sources hobart-python`.

## Files

| File | What it is |
|---|---|
| `sources.yaml` | the sources and settings |
| `ledger.yaml` | every event ever proposed (written by the collector; edit only to let an event back in) |
| `ignore.yaml` | links and patterns never to add |
| `.cache/` | cached AI answers (not committed; GitHub Actions keeps it between runs) |
| `hellotas_collector/` | the code: `sources/` (one file per kind), `rules.py`, `ai.py`, `store.py`, `pipeline.py` |
