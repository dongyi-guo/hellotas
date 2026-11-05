import json

from conftest import HOBART, NOW, FakeFetcher, fixture

from hellotas_collector.extract import event_from_jsonld, jsonld_event_objects, links_in_text
from hellotas_collector.sources import Context, acs, aisa, ical, jsonld
from hellotas_collector.sources.page import dates_in, is_no_fetch, mentions_upcoming_date


def ctx(pages, **kwargs):
    return Context(fetcher=FakeFetcher(pages), tz=HOBART, now=NOW, **kwargs)


def test_gdg_jsonld_event():
    objs = jsonld_event_objects(fixture("gdg_event.html"))
    ev = event_from_jsonld(objs[0], "https://gdg.community.dev/e/x/", "gdg-hobart", HOBART)
    assert ev.title == "DevFest 2026: Explore AI Powered Development & Digital Analytics"  # &amp; undone
    assert ev.start.isoformat() == "2026-11-19T17:15:00+11:00"
    assert ev.end.isoformat() == "2026-11-19T18:45:00+11:00"
    assert ev.attendance == "in_person" and ev.region == "TAS"
    assert ev.free is True and ev.cost == "Free"


def test_gdg_source_prefers_the_real_banner():
    cfg = {"id": "gdg-hobart", "listing": "https://gdg.community.dev/gdg-hobart/",
           "follow": r"^https://gdg\.community\.dev/events/details/",
           "image_exclude": ["SocialSharingThumbnail"], "page_images": "/v1/gcs/platform-data-goog/events/"}
    event_url = "https://gdg.community.dev/events/details/google-gdg-hobart-presents-devfest-2026/"
    listing = f'<a href="{event_url}">DevFest</a><a href="https://gdg.community.dev/about/">About</a>'
    events = jsonld.collect(cfg, ctx({cfg["listing"]: listing, event_url: fixture("gdg_event.html")}))
    assert len(events) == 1
    assert "/events/" in events[0].images[0]
    assert not any("SocialSharingThumbnail" in u for u in events[0].images)


def test_humanitix_offset_without_colon():
    objs = jsonld_event_objects(fixture("humanitix_event.html"))
    ev = event_from_jsonld(objs[0], "https://events.humanitix.com/ict-awards-night", "x", HOBART)
    assert ev.start.isoformat() == "2026-11-09T17:30:00+11:00"
    assert ev.attendance == "in_person"
    assert "Stanley Burbury" in ev.location_name


def test_eventbrite_itemlist_is_date_only():
    objs = jsonld_event_objects(fixture("eventbrite_listing.html"))
    assert len(objs) >= 5
    ev = event_from_jsonld(objs[0], "https://www.eventbrite.com.au/d/x/", "eb", HOBART)
    assert ev.all_day is True and ev.start.hour == 0


def test_meetup_links_hidden_in_page_data():
    found = links_in_text(fixture("meetup_listing.html"), r"^https://www\.meetup\.com/sectalks-hobart/events/\d+/?$")
    assert found == ["https://www.meetup.com/sectalks-hobart/events/317249458/",
                     "https://www.meetup.com/sectalks-hobart/events/316864389/"]


def test_acs_filters_and_prices():
    cfg = {"id": "acs", "listing": "https://acs.example/list.json", "detail_url": "https://acs.example/detail.html",
           "states": ["TAS"], "exclude_types": ["Short Courses"],
           "exclude_titles": r"(?i)annual general meeting|\bAGM\b", "skip_member_only": True,
           "defaults": {"host": "ACS", "topics": ["careers"]}}
    data = json.loads(fixture("acs_events.json"))
    pages = {cfg["listing"]: json.dumps(data)}
    beyond = next(e for e in data["events"] if e["eventTitle"].startswith("Beyond Graduation"))
    pages[f"{cfg['detail_url']}?eventId={beyond['eventId']}"] = fixture("acs_detail.html")
    events = acs.collect(cfg, ctx(pages))
    titles = [e.title for e in events]
    assert any(t.startswith("How to get a job in IT Support") for t in titles)  # online: kept
    assert not any("Cybersecurity Then and Now" in t for t in titles)  # in person in QLD: dropped
    assert not any("Applied AI" in t for t in titles)  # short course: dropped
    assert not any("Annual General Meeting" in t for t in titles)  # AGM: dropped
    assert not any("Coffee With ACS NT" in t for t in titles)  # members only: dropped
    ev = next(e for e in events if e.title.startswith("Beyond Graduation"))
    assert ev.cost == "Free for ACS members · $15 for non-members"
    assert ev.start.isoformat() == "2026-12-10T18:00:00+11:00"
    assert "Alannah Grech, Student and Graduate Success Manager, for" in ev.description


def test_aisa_page_inside_one_big_form():
    ev = aisa.parse_event_page(fixture("aisa_event.html"), "https://www.aisa.org.au/Event.aspx?EventKey=OB281026",
                               "aisa", HOBART)
    assert ev is not None
    assert ev.title == "AISA Webinar: When Attackers Use AI: How defenders can respond"
    assert ev.start.isoformat() == "2026-11-25T12:00:00+11:00"
    assert ev.end.isoformat() == "2026-11-25T13:00:00+11:00"
    assert ev.online is True and ev.host == "AISA Online Branch"
    assert ev.cost == "Free for AISA members"


def test_aisa_collect_dedupes_branches():
    url = "https://www.aisa.org.au/Event.aspx?EventKey=OB281026"
    cfg = {"id": "aisa", "branches": {"Hobart": "https://a.example/hobart", "Online": "https://a.example/online"}}
    pages = {"https://a.example/hobart": fixture("aisa_listing.html"),
             "https://a.example/online": fixture("aisa_listing.html"), url: fixture("aisa_event.html")}
    c = ctx(pages)
    events = aisa.collect(cfg, c)
    assert len(events) == 1
    assert c.fetcher.asked.count(url) == 1


ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:a@test
SUMMARY:Tas ICT careers expo
DTSTART;VALUE=DATE:20261201
DTEND;VALUE=DATE:20261203
URL:https://careerify.example/events/expo
LOCATION:Hobart Function Centre
END:VEVENT
BEGIN:VEVENT
UID:b@test
SUMMARY:Cyber meetup
DTSTART;TZID=Australia/Hobart:20261112T173000
DTEND;TZID=Australia/Hobart:20261112T190000
URL:https://careerify.example/events/cyber
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


def test_ical_all_day_end_is_last_day():
    events = ical.parse_calendar(ICS, "careerify", HOBART)
    expo, cyber = events
    assert expo.all_day and expo.start.isoformat() == "2026-12-01T00:00:00+11:00"
    assert expo.end.isoformat() == "2026-12-02T23:59:00+11:00"  # DTEND is exclusive
    assert cyber.start.isoformat() == "2026-11-12T17:30:00+11:00" and cyber.status == "cancelled"


def test_dates_and_no_fetch_hosts():
    assert (2026, 12, 16) in dates_in("Tuesday, 16th December 2026, 5:00PM")
    assert (2026, 11, 25) in dates_in("When 25/11/2026 12:00 PM")
    assert not mentions_upcoming_date("Held on 16 December 2025.", NOW)
    assert mentions_upcoming_date("Next one: 3 March 2027", NOW)
    assert is_no_fetch("https://www.linkedin.com/posts/someone_activity-123")
    assert not is_no_fetch("https://events.humanitix.com/x")
