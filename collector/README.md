# Event collector

Finds upcoming ICT events for the Happening page and writes them into `data/happening/`, in the same format as
the hand-written entries. It replaces the manual sessions where someone browsed each organiser's site and copied
the details across.

It runs by itself every morning (GitHub Actions), and whenever someone suggests an event with the
**Suggest an event** issue form.

```
 sources.yaml ──► read each source ──► drop: past, too far ahead, already listed, rejected before
                                         │
                                         ▼
                       judge relevance with keyword rules (60/100 or more)
                                         │
                                         ▼
       write the entry in English + download the organiser's picture (or borrow one, see below)
                                         │
                                         ▼
     data/happening/<slug>.yaml + picture + ledger line ──► pull request (or straight to the site)
```

**No AI is used for now.** The team isn't paying for an AI service, so the AI step is switched off
(`ai.enabled: false` in `sources.yaml`) and any API key is ignored. Entries are written in English; add Chinese and
Nepali in the pull request if you like (until then those pages show the English text). The AI step stays in the code,
ready for when someone can fund it: see [Switching the AI on](#switching-the-ai-on).

## What it reads

| Source | How | Notes |
|---|---|---|
| GDG Hobart | event pages' schema.org data | `gdg.community.dev/api/` is disallowed in robots.txt, so it reads the public pages instead |
| ACS | the JSON list behind the ACS events page, then each event page for prices | online events from anywhere, in-person ones only in Tasmania; no short courses, AGMs or members-only events |
| AISA (Hobart and Online branches) | branch pages and event pages (plain HTML) | |
| SecTalks Hobart | Meetup event pages' schema.org data | Meetup keeps its event links in page data, which the collector reads |
| TasICT | event pages, then the Humanitix registration page they link to | pages with no event data and no registration link are skipped |
| Careerify (Tasmanian Government) | iCalendar feed | its firewall refuses some cloud networks; the run summary says when |
| Eventbrite (Hobart, science and tech) | listing page | **off**: mostly children's and library events, and Eventbrite's terms restrict automated access |
| UTAS events | | **off**: utas.edu.au answers every automated request with a Cloudflare challenge |

All sources were checked in November 2026. Every page the collector opens is allowed by that site's robots.txt
for its user agent (`hellotas-collector/1.0 (+https://github.com/dongyi-guo/hellotas)`), and it waits 1.5 seconds
between requests to the same site. When a site blocks it, it reports that and moves on; it never disguises
itself or works around a block.

**LinkedIn** (upstream issue 62) forbids automated access in its terms and robots.txt, so the collector never
opens LinkedIn links. Most LinkedIn event posts link to a Humanitix, Eventbrite or Meetup page: suggest that link
instead and it is read automatically. If there is no such link, a maintainer adds the event by hand from the
details pasted into the form.

## How it decides

**Duplicates** are caught three ways: the same link as any upcoming *or archived* event (including the links under
`references` in `data/events/`), the same day with a similar title (so GDG Hobart's Bevy page and its Meetup copy
count as one), and `ledger.yaml`, which lists every event the collector has ever proposed. If a proposed event's
file is gone, someone removed it on purpose and it is not proposed again.

**Relevance** is a score from 0 to 100; 60 or more is added (`min_relevance` in `sources.yaml`). Keyword rules
(`hellotas_collector/rules.py`) score the title and short description: the source's trust level, ICT topics, signs
the event is meant for students, its location (Tasmania or online, not in person interstate), and signs it isn't
for students (AGMs, short courses, children, executive breakfasts). The rules were tuned against the events the team
picked by hand from the same sources, and they match those picks. Suggestions from people are always proposed.

**Writing**: the title as the organiser wrote it, and a summary from the organiser's opening sentences (greetings,
exclamation marks and cut-off sentences removed).

**Pictures**: every event gets one, and `hellotas-collect check-data` (run by the Tests workflow) fails if an
upcoming event has none. The collector downloads the organiser's own picture when the site allows it. When it
can't (Meetup and ACS don't allow their images to be downloaded automatically), it copies the most recent picture
already used for the same organiser, or failing that the `default_image` in `sources.yaml`. The pull request says
which events have a borrowed picture, so someone can replace it with the event's own.

The collector never overwrites what people wrote. The only thing it changes in an existing file is `start` and
`end`, and only in files it created (they have a `source:` line), when the organiser changes the date.

## Setting it up on GitHub

1. **Allow pull requests from Actions**: Settings > Actions > General > Workflow permissions > *Read and write
   permissions*, and tick *Allow GitHub Actions to create and approve pull requests*.
2. **Turn on Issues** (Settings > General > Features), so the **Suggest an event** form works.
3. **Optional: publish without review.** Variable `COLLECTOR_PUBLISH` = `true` (Settings > Secrets and variables >
   Actions > Variables). Leave it off for the first few weeks and check the pull requests first.
4. **Optional: Discord.** Secret `DISCORD_WEBHOOK_URL` (Discord: Server settings > Integrations > Webhooks). After
   each deploy, events that are new on the site are posted to that channel.

Then run it once by hand: Actions > Collect events > Run workflow.

## Reviewing what it proposes

The collector keeps one pull request open, **New events from the collector**, and adds to it each day.

- Merge it to publish everything in it.
- Delete a file in the pull request to drop that event; its ledger line keeps it from coming back.
- Edit any text in the branch (add translations, swap a borrowed picture); the collector won't touch it again,
  apart from `start` and `end`.
- Close the pull request to reject all of it: `collector-pr-closed.yml` copies its ledger lines to `main`.
- To let a rejected event back in, delete its line from `ledger.yaml`.
- To block a source or organiser for good, add a link or a pattern to `ignore.yaml`.

Pull requests opened by Actions don't start other workflows (a GitHub rule), so the Tests workflow doesn't run on
them automatically; run it from the Actions tab if you want it.

## Switching the AI on

Optional. Switched on, an AI model judges each event's relevance (instead of the keyword rules), writes the entry in
English, Chinese and Nepali in the style of the team's hand-written entries, and reads organiser pages that have no
event data. Everything it writes still arrives as a pull request for review. If the service fails, runs out of credit
or declines an event, the collector uses the keyword rules for that event and says so in the pull request.

It works with these services:

| `provider` | Service | Repository secret | Where to get a key |
|---|---|---|---|
| `anthropic` | Claude (Anthropic) | `ANTHROPIC_API_KEY` | console.anthropic.com |
| `openai` | ChatGPT models (OpenAI API) | `OPENAI_API_KEY` | platform.openai.com |
| `gemini` | Google Gemini | `GEMINI_API_KEY` | aistudio.google.com |
| `openai-compatible` | any service with an OpenAI-style API: OpenRouter, DeepSeek, Groq, Mistral and others | `AI_API_KEY` | the service's own site |

A ChatGPT Plus or Claude Pro subscription doesn't include API access: the API is billed separately, by use. Some
providers offer a free tier with lower limits; read its terms first, including how free-tier data may be used.

**Steps:**

1. **Get an API key** from the service and, if it is paid, set a monthly spending limit in its billing settings.
2. **Add the key as a repository secret**: Settings > Secrets and variables > Actions > Secrets > *New repository
   secret*, named as in the table.
3. **Edit the `ai:` block in `collector/sources.yaml`**:
   ```yaml
   ai:
     enabled: true
     provider: "openai"          # anthropic, openai, gemini or openai-compatible
   ```
   For `openai-compatible`, also set the service's address and model, for example:
   ```yaml
     provider: "openai-compatible"
     models:
       openai-compatible: "deepseek-chat"
     base_url: "https://api.deepseek.com"
   ```
4. **Check the model name** under `models:` against the provider's current model list; providers rename and retire
   models. The repository variables `COLLECTOR_MODEL` and `COLLECTOR_AI_PROVIDER` override the file, which is handy
   for trying a model without a commit.
5. **Run it once by hand**: Actions > Collect events > Run workflow. The pull request's last line shows the provider,
   the model, the number of calls and the tokens used, so you can see what a run costs.

With `openai`, if the model rejects the reasoning setting (models without reasoning, such as `gpt-4.1`), set
`send_effort: false`. To switch the AI off again, set `enabled: false`; the key can stay.

**What a run uses:** two calls per new event (relevance, then the write-up) and one per page without event data.
Answers are cached, so an unchanged event is never paid for twice. Most days find zero to three new events.

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
hellotas-collect check-data             # does every upcoming event have a picture?
pytest collector -q                     # tests (no network needed)
```

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
| `sources.yaml` | the sources and settings (including `default_image` and the switched-off `ai` block) |
| `ledger.yaml` | every event ever proposed (written by the collector; edit only to let an event back in) |
| `ignore.yaml` | links and patterns never to add |
| `hellotas_collector/` | the code: `sources/` (one file per kind), `rules.py`, `store.py`, `pipeline.py`, and the optional AI step: `ai.py` (the prompts) and `providers.py` (one class per AI service) |
