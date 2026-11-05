import glob
import io
from pathlib import Path

from conftest import HOBART, REPO

from hellotas_collector import rules
from hellotas_collector.model import RawEvent
from hellotas_collector.store import Site, build_entry, dump, update_dates, yaml
from hellotas_collector.text import first_sentences, no_em_dash, slugify, title_similarity, url_key
from hellotas_collector.extract import parse_when


def test_url_key_ignores_noise_but_keeps_event_ids():
    a = "https://events.humanitix.com/ict-awards-night?accesscode=STUDENT&utm_source=x"
    assert url_key(a) == url_key("http://events.humanitix.com/ict-awards-night/")
    acs1 = "https://www.acs.org.au/cpd-education/event-detail.html?eventId=701Om00000nhlVhIAI"
    acs2 = "https://www.acs.org.au/cpd-education/event-detail.html?eventId=701Om00000oQCOyIAO"
    assert url_key(acs1) != url_key(acs2)
    assert url_key(acs1) == url_key(acs1.replace("https://www.", "http://"))


def test_title_similarity_survives_platform_differences():
    assert title_similarity("DevFest 2026: Explore AI Powered Development & Digital Analytics",
                            "GDG Hobart DevFest 2026: AI-Powered Development & Digital Analytics") > 0.6
    assert title_similarity("SecTalks Hobart November", "ACS Professional Year webinar") < 0.4


def test_house_style_text():
    assert no_em_dash("Career Toolkit — Public Speaking") == "Career Toolkit, Public Speaking"
    assert no_em_dash("职业工具箱：找到你的声音——新晋专业人士", "zh") == "职业工具箱：找到你的声音，新晋专业人士"
    s = first_sentences("Happy November, SecTalkers! This month Ben will discuss email spoofing! There is no need to b")
    assert s == "This month Ben will discuss email spoofing."
    assert slugify("How to Get a Job in Data: What Employers Want") == "how-get-job-data-what-employers-want"


def _ev(**kw):
    base = dict(source="t", url="https://x.org/e", title="Event", start=parse_when("2026-11-20T18:00:00+11:00", HOBART)[0])
    base.update(kw)
    ev = RawEvent(**base)
    ev.extra.setdefault("trust", "medium")
    return ev


def test_rules_on_the_events_the_team_chose():
    career = _ev(title="How to get a job in IT Support: skills, pathways and opportunities", online=True,
                 attendance="online", description="Explore careers in IT Support and hear how people found jobs.")
    assert rules.judge(career).score >= 60 and rules.type_for(career) == "webinar"
    assert "careers" in rules.topics_for(career)
    kids = _ev(title="LEGO SPIKE team challenge at Hobart Library", region="TAS",
               description="For kids aged 8 to 12 during the school holidays.")
    kids.extra["trust"] = "low"
    assert rules.judge(kids).score < 30
    interstate = _ev(title="ACS Tech: Sustainable Data Centres", region="WA", attendance="in_person",
                     location_name="Perth")
    assert rules.judge(interstate).score < 60
    sectalks = _ev(title="SecTalks Hobart - November - Just spoof the government?", region="TAS",
                   location_name="Mathers House", description="Social engineering and email spoofing.")
    sectalks.extra.update(trust="high", default_type="meetup")
    assert rules.type_for(sectalks) == "meetup"  # "SecTalks" is not the word "talks"
    assert "development" not in rules.topics_for(sectalks)


def test_existing_files_round_trip_byte_for_byte():
    y = yaml()
    files = glob.glob(str(REPO / "data" / "happening" / "*.yaml")) + glob.glob(str(REPO / "data" / "events" / "*" / "*.yaml"))
    assert files
    for f in files:
        src = Path(f).read_text(encoding="utf-8")
        buf = io.StringIO()
        y.dump(y.load(src), buf)
        assert buf.getvalue() == src, f


def test_new_entry_matches_house_style():
    ev = _ev(url="https://www.meetup.com/sectalks-hobart/events/1/", source="sectalks-hobart",
             end=parse_when("2026-11-20T20:00:00+11:00", HOBART)[0])
    fields = {"title": {"en": "SecTalks Hobart: Email spoofing"}, "type": "meetup", "format": "in_person",
              "topics": ["cyber", "community"], "host": "SecTalks Hobart",
              "location": {"en": "Mathers House, 108 Bathurst St, Hobart"},
              "cost": {"en": "Free", "zh": "免费", "ne": "निःशुल्क"}, "summary": {"en": "Ben explains email spoofing."}}
    text = dump(build_entry(fields, ev, HOBART, "/images/happening/x/x-1.jpg", "2026-11-05"))
    assert text.splitlines()[:6] == [
        "title:", '  en: "SecTalks Hobart: Email spoofing"', 'start: "2026-11-20T18:00:00+11:00"',
        'end: "2026-11-20T20:00:00+11:00"', 'type: "meetup"', 'format: "in_person"']
    assert "topics: [cyber, community]" in text and 'added: "2026-11-05"' in text and 'source: "sectalks-hobart"' in text


def test_match_by_link_and_by_title(site):
    s = Site(site, HOBART)
    by_link = _ev(url="https://www.acs.org.au/cpd-education/event-detail.html?eventId=701Om00000oQCOyIAO")
    assert s.match(by_link)[0].slug == "acs-get-a-job-in-data"
    meetup_copy = _ev(url="https://www.meetup.com/gdg-hobart/events/999/",
                      title="GDG Hobart DevFest 2026 - Explore AI Powered Development and Digital Analytics",
                      start=parse_when("2026-11-19T17:15:00+11:00", HOBART)[0])
    entry, how = s.match(meetup_copy)
    assert entry.slug == "gdg-hobart-devfest-2026" and how == "same date, similar title"
    archived = _ev(url="https://www.linkedin.com/posts/yu-wang-solana_one-of-the-most-valuable-ai-events-in-activity-7470375651292864513-dnJ-/")
    assert s.match(archived)[0].kind == "archive"  # links under `references` count too


def test_update_dates_only_on_collector_files(site):
    s = Site(site, HOBART)
    hand_made = next(e for e in s.entries if e.slug == "acs-get-a-job-in-data")
    moved = _ev(start=parse_when("2027-03-02T17:30:00+11:00", HOBART)[0])
    assert update_dates(hand_made, moved, HOBART) == []
    hand_made.data["source"] = "acs"  # pretend the collector wrote it
    changes = update_dates(hand_made, moved, HOBART)
    assert changes and "2027-03-02T17:30:00+11:00" in hand_made.path.read_text(encoding="utf-8")
