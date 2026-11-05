import json
from types import SimpleNamespace

from conftest import NOW, FakeFetcher, fixture

from hellotas_collector import issue_form
from hellotas_collector.config import load
from hellotas_collector.pipeline import Collector
from hellotas_collector.report import markdown

GDG_LISTING = "https://gdg.community.dev/gdg-hobart/"
SECTALKS_LISTING = "https://www.meetup.com/sectalks-hobart/events/"
SECTALKS_EVENT = "https://www.meetup.com/sectalks-hobart/events/317249458/"


def _pages():
    return {
        SECTALKS_LISTING: fixture("meetup_listing.html"),
        SECTALKS_EVENT: fixture("meetup_event.html"),
    }


def collector(site, pages=None, **kwargs):
    config = load(site / "collector" / "sources.yaml")
    kwargs.setdefault("use_ai", False)
    return Collector(site, config, now=NOW, fetcher=FakeFetcher(pages or _pages()), images=False, log=lambda *a: None,
                     **kwargs)


def test_past_event_is_skipped(site):
    # The fixture is a real Meetup page for 11 December 2025, before NOW
    result = collector(site).run(["sectalks-hobart"])
    assert result.found["sectalks-hobart"] == 1
    assert not result.added
    assert [s.why for s in result.skipped] == ["over"]


def _future_meetup(site):
    """The Meetup fixture with its date moved into the future."""
    html = fixture("meetup_event.html").replace("2025-12-11", "2026-11-10").replace("2025-12-11", "2026-11-10")
    return {SECTALKS_LISTING: fixture("meetup_listing.html"), SECTALKS_EVENT: html}


def test_new_event_then_never_again(site):
    c = collector(site, _future_meetup(site))
    result = c.run(["sectalks-hobart"])
    assert len(result.added) == 1, markdown(result)
    proposal = result.added[0]
    path = site / proposal.file_path
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Added by the event collector from SecTalks Hobart")
    assert 'source: "sectalks-hobart"' in text and 'url: "https://www.meetup.com/sectalks-hobart/events/317249458/"' in text
    assert (site / "collector" / "ledger.yaml").exists()

    # Second run: already listed
    again = collector(site, _future_meetup(site)).run(["sectalks-hobart"])
    assert not again.added and any(s.why == "already listed" for s in again.skipped)

    # A maintainer deletes the file: the ledger keeps it out, and its page isn't even opened again
    path.unlink()
    c3 = collector(site, _future_meetup(site))
    third = c3.run(["sectalks-hobart"])
    assert not third.added
    assert SECTALKS_EVENT not in c3.fetcher.asked


def test_dry_run_writes_nothing(site):
    before = sorted(p.name for p in (site / "data" / "happening").iterdir())
    result = collector(site, _future_meetup(site), dry_run=True).run(["sectalks-hobart"])
    assert len(result.added) == 1
    assert sorted(p.name for p in (site / "data" / "happening").iterdir()) == before
    assert not (site / "collector" / "ledger.yaml").exists()


def test_blocked_source_is_reported_not_fatal(site):
    from hellotas_collector.fetch import Blocked
    pages = _future_meetup(site)
    pages["https://careerify.tas.gov.au/events/tag/ict-events/list/?ical=1"] = Blocked("refuses automated visitors")
    result = collector(site, pages).run(["careerify", "sectalks-hobart"])
    assert "blocked" in result.errors["careerify"]
    assert len(result.added) == 1


# -- AI ---------------------------------------------------------------------------------------------------------

class FakeAnthropic:
    """Stands in for anthropic.Anthropic(): returns canned JSON per task and records each request."""

    def __init__(self, refuse=False):
        self.requests = []
        self.refuse = refuse
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **params):
        self.requests.append(params)
        system = params["system"][0]["text"]
        if self.refuse:
            return SimpleNamespace(stop_reason="refusal", content=[], usage=None)
        if "score its relevance" in system:
            answer = {"relevant": True, "score": 88, "reason": "Local cyber security meetup open to students."}
        else:
            answer = {
                "title": {"en": "SecTalks Hobart: Just Spoof the Government?", "zh": "SecTalks Hobart：冒充政府邮件？",
                          "ne": "SecTalks Hobart: सरकारलाई नक्कल गर्ने?"},
                "summary": {"en": "Ben walks through a real engagement — social engineering and email spoofing.",
                            "zh": "Ben 分享一次真实的渗透测试——社会工程学与邮件伪造。", "ne": "Ben ले सामाजिक इन्जिनियरिङ र इमेल स्पुफिङबारे बताउनुहुन्छ।"},
                "location": {"en": "Mathers House, 108 Bathurst Street, Hobart", "zh": "", "ne": ""},
                "cost": {"en": "Free", "zh": "免费", "ne": "निःशुल्क"},
                "host": "SecTalks Hobart", "slug": "sectalks-hobart-email-spoofing", "type": "meetup",
                "format": "in_person", "topics": ["cyber", "community", "made-up-topic"],
            }
        usage = SimpleNamespace(input_tokens=1200, output_tokens=300)
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text=json.dumps(answer, ensure_ascii=False))])


def test_ai_request_shape_and_output(site):
    fake = FakeAnthropic()
    c = collector(site, _future_meetup(site), use_ai=True, client=fake)
    result = c.run(["sectalks-hobart"])
    assert len(result.added) == 1
    p = result.added[0]
    assert p.written_by == "ai" and p.judgement.by == "ai" and p.slug == "sectalks-hobart-email-spoofing"
    req = fake.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["output_config"]["effort"] == "low"  # triage
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in req and "thinking" not in req
    assert fake.requests[1]["output_config"]["effort"] == "medium"  # write-up
    text = (site / p.file_path).read_text(encoding="utf-8")
    assert "—" not in text  # house style enforced even when the model slips
    assert "zh: \"SecTalks Hobart：冒充政府邮件？\"" in text
    assert "topics: [cyber, community]" in text  # unknown topic dropped
    assert result.ai["calls"] == 2


def test_ai_answers_are_cached(site):
    fake = FakeAnthropic()
    collector(site, _future_meetup(site), use_ai=True, client=fake, dry_run=True).run(["sectalks-hobart"])
    assert len(fake.requests) == 2
    (site / "collector" / ".cache" / "ai-cache.json").exists()
    fake2 = FakeAnthropic()
    result = collector(site, _future_meetup(site), use_ai=True, client=fake2, dry_run=True).run(["sectalks-hobart"])
    assert fake2.requests == [] and result.ai["cache_hits"] == 2


def test_haiku_gets_no_fallbacks(site, monkeypatch):
    monkeypatch.setenv("COLLECTOR_MODEL", "claude-haiku-5-5")
    fake = FakeAnthropic()
    collector(site, _future_meetup(site), use_ai=True, client=fake, dry_run=True).run(["sectalks-hobart"])
    assert fake.requests[0]["model"] == "claude-haiku-5-5" and "fallbacks" not in fake.requests[0]


def test_refusal_falls_back_to_rules(site):
    result = collector(site, _future_meetup(site), use_ai=True, client=FakeAnthropic(refuse=True)).run(
        ["sectalks-hobart"])
    assert len(result.added) == 1
    assert result.added[0].written_by == "rules" and result.added[0].judgement.by == "rules"


# -- suggestions -------------------------------------------------------------------------------------------------

ISSUE = """### Event link

https://www.linkedin.com/posts/someone_hobart-ai-meetup-activity-1234

### Event details

GDG Hobart: AI agents night, 3 December 2026, 5:30pm at The Forest building, UTAS.

### Why it's useful

_No response_
"""


def test_issue_form_parsing():
    s = issue_form.suggestion(ISSUE)
    assert s["url"].startswith("https://www.linkedin.com/posts/")
    assert "3 December 2026" in s["details"] and s["note"] == ""


def test_linkedin_is_never_fetched(site):
    c = collector(site, {})
    result = c.suggest("https://www.linkedin.com/posts/someone_x-activity-1", pasted_text="")
    assert "doesn't allow automated access" in result.errors["suggestion"]
    assert c.fetcher.asked == []


def test_suggested_humanitix_link_is_added_even_if_rules_unsure(site):
    url = "https://events.humanitix.com/ict-awards-night"
    c = collector(site, {url: fixture("humanitix_event.html")})
    result = c.suggest(url, note="School of ICT's own awards night")
    assert len(result.added) == 1
    assert result.added[0].judgement.by == "person"
    assert "School of ICT" in markdown(result, "Event suggestion")
