"""v2.1.2: one site owner, self sign-up, no list of accounts, and a one-time reset of logins that never touches
a league."""

import hashlib

from conftest import login
from f1tracker import auth, mailer, storage
from f1tracker.app import create_app


def _league_with_members(master_client):
    auth.create_user("carson", "Carson", "password1", email="carson@example.com")
    res = master_client.post("/careers/new", data={"name": "Kept League", "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Carson Hayes"], "player_login": ["carson"]})
    return res.headers["Location"].split("/career/")[1].split("/")[0]


def _digest(token):
    storage.checkpoint(token)
    return hashlib.sha256(storage.career_path(token).read_bytes()).hexdigest()


def test_reset_removes_every_login_and_touches_no_league(app, master_client, monkeypatch):
    token = _league_with_members(master_client)
    auth.set_setting("smtp_host", "smtp.example.com")
    before = _digest(token)
    removed = auth.reset_all_accounts(storage.backups_dir())
    assert removed == 2 and auth.user_count() == 0
    assert _digest(token) == before                                   # the league file is byte-for-byte the same
    assert list(storage.backups_dir().glob("accounts-before-2.1.2-reset-*.db"))
    assert auth.get_setting("smtp_host") == "smtp.example.com"        # site settings kept
    assert auth.reserved("carson") and auth.reserved("david")
    assert auth.reset_all_accounts(storage.backups_dir()) == 0         # only ever once
    # The real server runs it when it starts (tests don't).
    monkeypatch.setattr(auth, "reset_all_accounts", lambda d: (_ for _ in ()).throw(AssertionError("ran")))
    create_app({"TESTING": True, "SECRET_KEY": "x"})


def test_the_server_resets_logins_once_on_start(tmp_path):
    auth.create_user("old", "Old", "password1")
    create_app({"SECRET_KEY": "x"})
    assert auth.user_count() == 0
    auth.create_user("owner", "Owner", "password1", is_master=True)
    create_app({"SECRET_KEY": "x"})
    assert auth.get_user("owner")                                     # not again


def test_owner_is_made_with_the_setup_code_and_gets_their_leagues_back(app, master_client, monkeypatch):
    token = _league_with_members(master_client)
    auth.reset_all_accounts(storage.backups_dir())
    c = app.test_client()
    assert c.get("/").headers["Location"].endswith("/setup")
    monkeypatch.setenv("RENDER", "true")                              # a hosted site with no setup code: refused
    page = c.get("/setup").get_data(as_text=True)
    assert "F1_TRACKER_SETUP_CODE" in page
    monkeypatch.setenv("F1_TRACKER_SETUP_CODE", "secret-code")
    with c.session_transaction() as s:
        s["csrf"] = "tok"
    form = {"csrf_token": "tok", "username": "david", "display_name": "David", "password": "password1",
            "confirm_password": "password1", "setup_code": "wrong"}
    c.post("/setup", data=form)
    assert auth.user_count() == 0
    c.post("/setup", data={**form, "setup_code": "secret-code"})
    owner = auth.get_user("david")
    assert owner and owner["is_owner"] and owner["is_master"] and not auth.reserved("david")
    assert c.get(f"/career/{token}/dashboard").status_code == 200


def test_old_members_reclaim_their_name_only_with_the_same_verified_email(app, master_client, monkeypatch):
    token = _league_with_members(master_client)
    auth.reset_all_accounts(storage.backups_dir())
    auth.create_user("david", "David", "password1", is_master=True)
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, *a, **k: sent.append(body))

    def sign_up(email):
        c = app.test_client()
        with c.session_transaction() as s:
            s["csrf"] = "tok"
        c.post("/register", data={"username": "carson", "display_name": "Carson", "email": email,
                                  "password": "password1", "confirm": "password1", "csrf_token": "tok"})
        return c
    sign_up("stranger@example.com")
    assert not sent                                                    # refused before any code is sent
    c = sign_up("carson@example.com")
    code = sent[-1].split("code is: ")[1][:6]
    with c.session_transaction() as s:      # signing up starts a fresh session
        s["csrf"] = "tok"
    c.post("/register/verify", data={"code": code, "csrf_token": "tok"})
    assert auth.get_user("carson") and not auth.reserved("carson")
    assert c.get(f"/career/{token}/dashboard").status_code == 200      # memberships come straight back


def test_owner_finds_one_account_and_can_release_a_name_but_never_lists_them(app, master_client):
    _league_with_members(master_client)
    auth.create_user("zed", "Zed", "password1", email="zed@example.com")
    page = master_client.get("/accounts").get_data(as_text=True)
    assert "zed" not in page and "carson" not in page and "Account recovery" in page
    assert "Zed" in master_client.get("/accounts?find=ZED@example.com").get_data(as_text=True)
    assert "No account matches" in master_client.get("/accounts?find=ze").get_data(as_text=True)   # exact only
    master_client.post("/accounts/zed/delete", data={"csrf_token": "tok"})
    assert not auth.get_user("zed") and auth.reserved("zed")
    master_client.post("/accounts/release", data={"csrf_token": "tok", "username": "zed"})
    assert not auth.reserved("zed")
    # Members: no one else can reach recovery, and nobody sees a login dropdown anywhere.
    member = app.test_client()
    login(member, "carson")
    assert member.get("/accounts?find=david").get_data(as_text=True).count("Account recovery") == 0
    assert member.post("/accounts/release", data={"csrf_token": "tok", "username": "x"}).status_code in (302, 403)
    assert "/accounts/new" not in page


def test_league_pages_ask_for_a_username_instead_of_listing_everyone(app, master_client):
    token = _league_with_members(master_client)
    auth.create_user("hidden", "Hidden Person", "password1")
    page = master_client.get(f"/career/{token}/members").get_data(as_text=True)
    assert "Hidden Person" not in page and 'name="username" required' in page
    assert "Hidden Person" not in master_client.get("/").get_data(as_text=True)
    master_client.post(f"/career/{token}/members/add", data={"csrf_token": "tok", "username": "hidden", "role": "member"})
    with storage.session(token) as conn:
        assert conn.execute("SELECT 1 FROM career_members WHERE username = 'hidden'").fetchone()

