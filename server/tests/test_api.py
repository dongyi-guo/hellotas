import hashlib
import re
from datetime import date, timedelta

from conftest import last_email, sign_in

from hellotas_api.models import LoginLink


# -- signing in ----------------------------------------------------------------------------------------------------

def test_only_university_addresses_can_sign_in(client):
    r = client.post("/v1/auth/request", json={"email": "someone@gmail.com"})
    assert r.status_code == 422 and "utas.edu.au" in r.json()["detail"]


def test_magic_link_works_once_and_hides_the_token_from_servers(client, app):
    client.post("/v1/auth/request", json={"email": "Student@UTAS.edu.au", "lang": "zh"})
    msg = last_email(app, "student@utas.edu.au")
    assert "https://site.example/zh/account/#signin=" in msg.text  # fragment: never sent to a server
    assert "登录" in msg.subject
    token = re.search(r"#signin=([\w-]+)", msg.text).group(1)
    first = client.post("/v1/auth/verify", json={"token": token})
    assert first.status_code == 200
    assert first.json()["user"]["email"] == "student@utas.edu.au"
    assert client.post("/v1/auth/verify", json={"token": token}).status_code == 400  # used
    db = app.state.sessionmaker()
    stored = [link.token_hash for link in db.query(LoginLink)]
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]  # only the hash is kept, never the link itself
    db.close()


def test_session_and_logout(client, app):
    h = sign_in(client, app, "a@utas.edu.au")
    assert client.get("/v1/me", headers=h).json()["role"] == "member"
    assert client.post("/v1/auth/logout", headers=h).status_code == 200
    assert client.get("/v1/me", headers=h).status_code == 401


def test_admin_addresses_become_admins(client, app):
    h = sign_in(client, app, "admin@utas.edu.au")
    assert client.get("/v1/me", headers=h).json()["role"] == "admin"


def test_sign_in_requests_are_rate_limited(client):
    codes = [client.post("/v1/auth/request", json={"email": "spam@utas.edu.au"}).status_code for _ in range(6)]
    assert codes[:5] == [202] * 5 and codes[5] == 429


# -- events and buddies --------------------------------------------------------------------------------------------

def test_marks_and_public_counts(client, app):
    h = sign_in(client, app, "a@utas.edu.au")
    r = client.put("/v1/events/gdg-hobart-devfest-2026/mark", json={"status": "going"}, headers=h)
    assert r.status_code == 200 and r.json()["going"] == 1 and r.json()["mine"] == "going"
    public = client.get("/v1/events/stats?ids=gdg-hobart-devfest-2026").json()["events"]["gdg-hobart-devfest-2026"]
    assert public == {"interested": 0, "going": 1, "buddies": 0}  # no "mine" without a session
    assert client.put("/v1/events/not-on-the-site/mark", json={"status": "going"}, headers=h).status_code == 404
    assert client.put("/v1/events/BAD..ID/mark", json={"status": "going"}, headers=h).status_code == 404
    assert client.put("/v1/events/gdg-hobart-devfest-2026/mark", json={"status": "maybe"}, headers=h).status_code == 422


def test_went_record_for_events_that_are_over(client, app):
    h = sign_in(client, app, "a@utas.edu.au")
    client.put("/v1/events/old-meetup/mark", json={"status": "going"}, headers=h)
    client.put("/v1/events/acs-get-a-job-in-data/mark", json={"status": "interested"}, headers=h)
    events = {e["event_id"]: e["status"] for e in client.get("/v1/me/events", headers=h).json()["events"]}
    assert events == {"old-meetup": "went", "acs-get-a-job-in-data": "interested"}


def test_buddies_share_emails_only_after_acceptance(client, app):
    alice = sign_in(client, app, "alice@utas.edu.au")
    bob = sign_in(client, app, "bob@utas.edu.au")
    client.patch("/v1/me", json={"display_name": "Alice W", "course": "Master of IT", "languages": "English, 中文"},
                 headers=alice)
    client.put("/v1/events/gdg-hobart-devfest-2026/buddy", json={"note": "First meetup, meet outside at 5:10?"},
               headers=alice)
    assert client.get("/v1/events/gdg-hobart-devfest-2026/buddies").status_code == 401  # signed-in users only
    listing = client.get("/v1/events/gdg-hobart-devfest-2026/buddies", headers=bob).json()["buddies"][0]
    assert listing["name"] == "Alice W" and "email" not in listing and listing["note"].startswith("First meetup")

    asked = client.post(f"/v1/events/gdg-hobart-devfest-2026/buddies/{listing['id']}/ask",
                        json={"message": "I'm new too!"}, headers=bob)
    assert asked.status_code == 201
    ask_email = last_email(app, "alice@utas.edu.au")
    assert "would like to go to GDG Hobart DevFest 2026 with you" in ask_email.subject
    assert "bob@utas.edu.au" not in ask_email.text  # not yet

    intro = client.get("/v1/me/intros", headers=alice).json()["intros"][0]
    assert intro["direction"] == "incoming" and "email" not in intro
    assert client.post(f"/v1/intros/{intro['id']}", json={"accept": True}, headers=bob).status_code == 404  # not Bob's
    assert client.post(f"/v1/intros/{intro['id']}", json={"accept": True}, headers=alice).json()["status"] == "accepted"
    assert "alice@utas.edu.au" in last_email(app, "bob@utas.edu.au").text
    assert "bob@utas.edu.au" in last_email(app, "alice@utas.edu.au").text
    assert client.get("/v1/me/intros", headers=bob).json()["intros"][0]["email"] == "alice@utas.edu.au"
    assert client.get("/v1/events/stats?ids=gdg-hobart-devfest-2026").json()["events"][
        "gdg-hobart-devfest-2026"]["buddies"] == 1


def test_cannot_ask_yourself(client, app):
    alice = sign_in(client, app, "alice@utas.edu.au")
    client.put("/v1/events/gdg-hobart-devfest-2026/buddy", json={"note": ""}, headers=alice)
    lid = client.get("/v1/events/gdg-hobart-devfest-2026/buddies", headers=alice).json()["buddies"][0]["id"]
    assert client.post(f"/v1/events/gdg-hobart-devfest-2026/buddies/{lid}/ask", json={},
                       headers=alice).status_code == 400


# -- walls, opportunities and moderation -----------------------------------------------------------------------------

def test_posts_wait_for_a_moderator(client, app):
    student = sign_in(client, app, "s@utas.edu.au")
    mod = sign_in(client, app, "admin@utas.edu.au")
    r = client.post("/v1/posts", json={"kind": "wish", "title": "A Rust meetup in Hobart",
                                       "body": "Monthly would be great.‮"}, headers=student)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert "‮" not in r.json()["body"]  # direction-override characters stripped
    assert client.get("/v1/posts?kind=wish").json()["posts"] == []
    assert client.get("/v1/posts?kind=wish", headers=student).json()["pending"][0]["title"] == "A Rust meetup in Hobart"
    assert client.get("/v1/mod/queue", headers=student).status_code == 403
    queue = client.get("/v1/mod/queue", headers=mod).json()
    pid = queue["posts"][0]["id"]
    assert client.post(f"/v1/mod/posts/{pid}", json={"action": "approve"}, headers=mod).json()["status"] == "approved"
    public = client.get("/v1/posts?kind=wish").json()["posts"][0]
    assert public["author"] == "s" and "author_email" not in public
    assert client.post(f"/v1/posts/{pid}/react", headers=student).json() == {"reactions": 1, "reacted": True}
    assert client.post(f"/v1/posts/{pid}/react", headers=student).json() == {"reactions": 0, "reacted": False}
    client.post(f"/v1/posts/{pid}/report", json={"reason": "duplicate"}, headers=mod)
    assert client.get("/v1/mod/queue", headers=mod).json()["reports"][0]["reason"] == "duplicate"


def test_opportunities_need_work_rights_and_close(client, app):
    mod = sign_in(client, app, "admin@utas.edu.au")
    base = {"kind": "opportunity", "title": "Graduate developer", "link": "https://jobs.example/grad",
            "organisation": "Example Pty Ltd", "opportunity_type": "graduate"}
    assert client.post("/v1/posts", json={**base, "work_rights": "whatever"}, headers=mod).status_code == 422
    assert client.post("/v1/posts", json={**base, "link": "", "work_rights": "anyone"}, headers=mod).status_code == 422
    assert client.post("/v1/posts", json={**base, "link": "javascript:alert(1)", "work_rights": "anyone"},
                       headers=mod).status_code == 422
    open_until = (date.today() + timedelta(days=7)).isoformat()
    closed = (date.today() - timedelta(days=1)).isoformat()
    client.post("/v1/posts", json={**base, "work_rights": "citizen_or_pr", "closes_on": open_until}, headers=mod)
    client.post("/v1/posts", json={**base, "title": "Closed one", "work_rights": "anyone", "closes_on": closed},
                headers=mod)
    posts = client.get("/v1/posts?kind=opportunity").json()["posts"]  # moderators' posts are approved directly
    assert [p["title"] for p in posts] == ["Graduate developer"]
    assert posts[0]["meta"]["work_rights"] == "citizen_or_pr"


# -- checklist, export, deletion --------------------------------------------------------------------------------------

def test_checklist_merges(client, app):
    h = sign_in(client, app, "a@utas.edu.au")
    client.post("/v1/me/checklist", json={"done": ["get-a-tfn", "open-a-bank-account", "Bad Id!"]}, headers=h)
    r = client.post("/v1/me/checklist", json={"done": ["get-a-sim"], "undone": ["get-a-tfn"]}, headers=h)
    assert r.json()["done"] == ["get-a-sim", "open-a-bank-account"]


def test_export_and_delete_everything(client, app):
    a = sign_in(client, app, "a@utas.edu.au")
    b = sign_in(client, app, "b@utas.edu.au")
    client.put("/v1/events/gdg-hobart-devfest-2026/mark", json={"status": "going"}, headers=a)
    client.put("/v1/events/gdg-hobart-devfest-2026/buddy", json={"note": "hi"}, headers=a)
    lid = client.get("/v1/events/gdg-hobart-devfest-2026/buddies", headers=b).json()["buddies"][0]["id"]
    client.post(f"/v1/events/gdg-hobart-devfest-2026/buddies/{lid}/ask", json={}, headers=b)
    client.post("/v1/posts", json={"kind": "achievement", "title": "Got my first IT job"}, headers=a)
    data = client.get("/v1/me/export", headers=a).json()
    assert data["account"]["email"] == "a@utas.edu.au" and len(data["events"]) == 1 and len(data["posts"]) == 1
    assert all("token_hash" not in row for row in data["buddy_requests"])
    assert client.delete("/v1/me", headers=a).json() == {"deleted": True}
    assert client.get("/v1/me", headers=a).status_code == 401
    assert client.get("/v1/events/stats?ids=gdg-hobart-devfest-2026").json()["events"][
        "gdg-hobart-devfest-2026"] == {"interested": 0, "going": 0, "buddies": 0}
    assert client.get("/v1/me/intros", headers=b).json()["intros"] == []


# -- digest ----------------------------------------------------------------------------------------------------------

def test_digest_double_opt_in_and_one_click_unsubscribe(client, app):
    assert client.post("/v1/digest/subscribe", json={"email": "anyone@gmail.com", "lang": "ne",
                                                     "topics": ["careers", "bogus"]}).status_code == 202
    confirm = re.search(r"(http\S+/v1/digest/confirm\?token=[\w-]+)", last_email(app, "anyone@gmail.com").text).group(1)
    assert client.post("/v1/admin/digest/send", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.post("/v1/admin/digest/send", headers={"Authorization": "Bearer cron-secret"}).json() == {"sent": 0}
    assert "subscribed" in client.get(confirm.replace("http://testserver", "")).text
    assert client.post("/v1/admin/digest/send", headers={"Authorization": "Bearer cron-secret"}).json() == {"sent": 1}
    digest = last_email(app, "anyone@gmail.com")
    assert "How to Get a Job in Data" in digest.text  # careers, within two weeks
    assert "GDG Hobart DevFest" not in digest.text  # not a chosen topic
    assert "Too far away" not in digest.text and "An event that is over" not in digest.text
    assert digest.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    unsubscribe = digest.headers["List-Unsubscribe"].strip("<>").replace("http://testserver", "")
    assert "Unsubscribed" in client.post(unsubscribe).text
    assert client.post("/v1/admin/digest/send", headers={"Authorization": "Bearer cron-secret"}).json() == {"sent": 0}


# -- suggestions -----------------------------------------------------------------------------------------------------

def test_suggestions(client, app):
    anon = client.post("/v1/suggestions", json={"url": "https://events.humanitix.com/x", "details": "Thu 5pm"})
    assert anon.status_code == 201 and anon.json()["status"] == "pending"
    assert client.post("/v1/suggestions", json={"url": "https://spam.example", "website": "http://bot"}).json() == {
        "status": "pending"}
    h = sign_in(client, app, "a@utas.edu.au")
    signed = client.post("/v1/suggestions", json={"url": "https://events.humanitix.com/y", "note": "Free pizza"},
                         headers=h).json()
    assert signed["status"] == "forwarded" and signed["issue_url"].endswith("/issues/99")
    call = app.state.http.calls[-1]
    assert call["url"] == "https://api.github.com/repos/dongyi-guo/hellotas/issues"
    assert call["json"]["title"].startswith("Event suggestion: ")
    assert "### Event link\n\nhttps://events.humanitix.com/y" in call["json"]["body"]
    mod = sign_in(client, app, "admin@utas.edu.au")
    pending = client.get("/v1/mod/queue", headers=mod).json()["suggestions"]
    assert [s["url"] for s in pending] == ["https://events.humanitix.com/x"]  # the bot one was never stored
    assert client.post(f"/v1/mod/suggestions/{pending[0]['id']}", json={"action": "forward"},
                       headers=mod).json()["status"] == "forwarded"


# -- the browser's view ----------------------------------------------------------------------------------------------

def test_cors_only_for_the_site(client):
    ok = client.options("/v1/events/stats", headers={"Origin": "https://site.example",
                                                      "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://site.example"
    other = client.options("/v1/events/stats", headers={"Origin": "https://evil.example",
                                                         "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in other.headers


def test_health_and_config(client):
    assert client.get("/health").json()["events_on_site"] == 4
    assert client.get("/v1/config").json()["email_domains"] == ["utas.edu.au"]
