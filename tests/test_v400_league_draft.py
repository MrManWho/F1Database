"""4.0.0-beta.4: a failed "Create league" keeps everything that was typed (it used to reset the setup page)."""

import json
import re

from conftest import login
from f1tracker import auth


def _client(app, name):
    c = app.test_client()
    login(c, name)
    return c


def _post(client, **extra):
    data = {"wizard": "1", "csrf_token": "tok", "name": "Night League", "year": "2026", "calendar": "standard",
            "player_name": ["Player One", "Jordan Vale"], "player_who": ["me", "invite"], "player_invite": ["", "nobody"],
            "preset": "simple", "join_mode": "invite", "visibility": "private", "notify_preset": "inapp",
            "invite_username": ["", ""], "invite_role": ["member", "spectator"], "league_description": "Thursdays"}
    data.update(extra)
    return client.post("/careers/new", data=data)


def test_a_failed_attempt_keeps_what_was_typed(app):
    auth.set_setting("league_creation", "everyone")
    auth.create_user("sam", "Sam", "password1")
    sam = _client(app, "sam")
    res = _post(sam)
    assert res.status_code == 302 and res.headers["Location"].endswith("/leagues/new")
    page = sam.get("/leagues/new").get_data(as_text=True)
    assert "no login called nobody" in page
    raw = re.search(r"data-draft='([^']*)'", page).group(1)
    draft = json.loads(raw.replace("&#34;", '"').replace("&amp;", "&").replace("&#39;", "'"))
    assert draft["step"] == 1                                            # opens at Players, where the problem is
    fields = draft["fields"]
    assert fields["name"] == ["Night League"] and fields["player_name"] == ["Player One", "Jordan Vale"]
    assert fields["player_invite"] == ["", "nobody"] and fields["league_description"] == ["Thursdays"]
    assert "csrf_token" not in fields
    # It's only used once: opening the page again starts fresh.
    assert "data-draft" not in sam.get("/leagues/new").get_data(as_text=True)
