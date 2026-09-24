"""v2.0 in a real browser: results entry tools, navigation on phones, keyboard use and unsaved-work guards."""

import pytest

from conftest import open_browser, players
from f1tracker import auth, roles, services as S, storage


def _league(master_client, name="Browser League"):
    auth.create_user("kim", "Kim", "password1")
    res = master_client.post("/careers/new", data={"name": name, "year": "2026", "csrf_token": "tok",
                                                   "player_name": ["Ana Silva"], "player_login": [""]})
    token = res.headers["Location"].split("/career/")[1].split("/")[0]
    with storage.session(token) as conn:
        roles.set_member(conn, "kim", "scorekeeper")
        storage.set_meta(conn, "timezone", "UTC")   # otherwise the Race Master's first visit detects it and reloads
        ev = S.events(conn, S.current_season_id(conn))[0]
    return token, ev


def _login(page, base, user="david"):
    page.goto(base + "/login")
    page.fill("input[name=username]", user)
    page.fill("input[name=password]", "password1")
    page.press("input[name=password]", "Enter")
    page.wait_for_load_state()
    page.evaluate("document.querySelectorAll('dialog[open]').forEach(d => d.close())")


def test_entry_tabs_search_copy_order_and_undo(app, master_client, live_server):
    token, ev = _league(master_client)
    pw, browser = open_browser()
    try:
        page = browser.new_context(viewport={"width": 1366, "height": 900}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _login(page, live_server, "kim")
        page.goto(f"{live_server}/career/{token}/weekend/{ev['id']}")
        q = page.locator('input[data-field="qualifying_position"]')
        r = page.locator('input[data-field="race_position"]')
        # Session tabs: only the chosen session's columns show.
        page.click('[data-session="q"]')
        assert q.first.is_visible() and not r.first.is_visible()
        page.click('[data-session="all"]')
        # Search keeps driver identity and narrows a big grid.
        page.fill("#entry-search", "lando")
        assert page.locator("#entry-table tbody tr:not(.search-miss)").count() == 1
        page.fill("#entry-search", "")
        # Fill qualifying, copy it to the race, then undo one change.
        n = q.count()
        for i in range(n):
            q.nth(i).fill(str(i + 1))
        page.select_option("#copy-order", "qualifying_position>race_position")
        page.wait_for_timeout(200)
        assert r.nth(3).input_value() == "4"
        r.nth(3).click(); r.nth(3).fill("9"); r.nth(3).press("Tab")
        assert r.nth(3).input_value() == "9"
        page.click("#undo-edit")
        assert r.nth(3).input_value() == "4"
        page.wait_for_timeout(1500)
        assert "Saved" in page.locator("#save-state").inner_text()
        with storage.session(token) as conn:
            saved = {row["driver_id"]: row["race_position"] for row in S.weekend_rows(conn, ev["id"])}
        assert sorted(saved.values()) == list(range(1, n + 1))
        assert errors == []
    finally:
        browser.close()
        pw.stop()


def test_phone_navigation_drawer_bottom_bar_and_palette(app, master_client, live_server):
    token, ev = _league(master_client)
    pw, browser = open_browser()
    try:
        page = browser.new_context(viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True).new_page()
        _login(page, live_server)
        page.goto(f"{live_server}/career/{token}/dashboard")
        assert page.locator(".bottom-nav").is_visible()
        assert not page.locator("#sidebar").is_visible() or page.locator("#sidebar").bounding_box()["x"] < -100
        page.click(".bottom-nav [data-open-menu]")
        page.wait_for_timeout(300)
        assert page.locator("#sidebar.open").count() == 1
        assert page.get_attribute("#menu-btn", "aria-expanded") == "true"
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert page.locator("#sidebar.open").count() == 0
        # No sideways scrolling on a phone.
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        # The search palette works from the keyboard.
        page.keyboard.press("Control+k")
        page.fill("#palette-q", "standings")
        with page.expect_navigation():          # Enter straight after typing still opens the right page
            page.keyboard.press("Enter")
        assert page.url.endswith("/standings")
    finally:
        browser.close()
        pw.stop()


def test_unsaved_results_warn_before_switching_mode_or_league(app, master_client, live_server):
    token, ev = _league(master_client)
    pw, browser = open_browser()
    try:
        page = browser.new_context(viewport={"width": 1366, "height": 900}).new_page()
        _login(page, live_server)
        page.goto(f"{live_server}/career/{token}/weekend/{ev['id']}")
        page.evaluate("window.F1.registerUnsaved(() => true)")   # as if an edit were still waiting to save
        page.click(".mode-switch summary")
        page.click('.mode-opt[value="scorekeeper"]')
        page.wait_for_timeout(300)
        assert page.locator("#confirm-dialog[open]").count() == 1          # asks first
        page.click("#confirm-cancel")
        assert "/weekend/" in page.url and page.locator(".mode-banner").count() == 0
        # Accessible dialog: focus returns and Escape closes it.
        page.keyboard.press("Control+k")
        assert page.evaluate("document.activeElement.id") == "palette-q"
        page.keyboard.press("Escape")
        assert page.locator("#palette[open]").count() == 0
    finally:
        browser.close()
        pw.stop()
