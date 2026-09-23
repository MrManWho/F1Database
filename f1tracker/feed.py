"""Paddock news headlines and per-player notifications, generated from what happens in the career."""

import threading
from pathlib import Path

from . import constants as C
from . import services as S
from .storage import now_iso


def _token(conn):
    try:
        return Path(conn.execute("PRAGMA database_list").fetchone()[2]).stem
    except Exception:
        return None


def post(conn, season_id, kind, headline, body="", link=None, driver_id=None, team_id=None, ref=None):
    conn.execute("""INSERT INTO news(season_id, kind, headline, body, link, driver_id, team_id, created_at, ref)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                 (season_id, kind, headline, body, link, driver_id, team_id, now_iso(), ref))
    token = _token(conn)
    if token and kind != "result":  # race results go to Discord as one summary instead
        from . import discord
        discord.queue_news(token, headline, body)


_outbox = threading.local()


def notify(conn, driver_id, text, link=None, ref=None):
    """driver_id None = everyone in the career."""
    conn.execute("INSERT INTO notifications(driver_id, text, link, created_at, ref) VALUES(?,?,?,?,?)",
                 (driver_id, text, link, now_iso(), ref))
    token = _token(conn)
    if token:
        if not hasattr(_outbox, "items"):
            _outbox.items = []
        _outbox.items.append((token, driver_id, text, link))


def take_outbox():
    """Notifications made during this request, for phone alerts once it has been saved."""
    items = getattr(_outbox, "items", [])
    _outbox.items = []
    return items


def delete_news(conn, news_id):
    conn.execute("DELETE FROM news WHERE id = ?", (news_id,))


def delete_notification(conn, notification_id):
    conn.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))


def delete_by_ref(conn, ref):
    conn.execute("DELETE FROM news WHERE ref = ?", (ref,))
    conn.execute("DELETE FROM notifications WHERE ref = ?", (ref,))


def latest(conn, limit=10, season_id=None):
    sql = "SELECT * FROM news" + (" WHERE season_id = ?" if season_id else "") + " ORDER BY id DESC LIMIT ?"
    params = (season_id, limit) if season_id else (limit,)
    tmap = S.team_map(conn)
    out = []
    for r in conn.execute(sql, params):
        r = dict(r)
        r["team"] = tmap.get(r["team_id"])
        out.append(r)
    return out


def _visible(driver_id):
    if driver_id is None:
        return "driver_id IS NULL", ()
    return "(driver_id IS NULL OR driver_id = ?)", (driver_id,)


def notifications_for(conn, username, driver_id, is_master=False, limit=15):
    where, params = ("1=1", ()) if is_master else _visible(driver_id)
    seen = conn.execute("SELECT last_seen_id FROM notification_reads WHERE username = ?", (username,)).fetchone()
    seen = seen["last_seen_id"] if seen else 0
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM notifications WHERE {where} ORDER BY id DESC LIMIT ?",
                                          (*params, limit))]
    dmap = S.driver_map(conn)
    for r in rows:
        r["unread"] = r["id"] > seen
        r["driver"] = dmap.get(r["driver_id"])
    unread = conn.execute(f"SELECT COUNT(*) FROM notifications WHERE {where} AND id > ?", (*params, seen)).fetchone()[0]
    return rows, unread


def mark_read(conn, username):
    top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM notifications").fetchone()[0]
    conn.execute("""INSERT INTO notification_reads(username, last_seen_id) VALUES(?, ?)
                    ON CONFLICT(username) DO UPDATE SET last_seen_id = excluded.last_seen_id""", (username, top))


# --------------------------------------------------------------------------- generators

def _career_before(conn, driver_id, event, condition):
    """How many earlier events (all seasons) the driver met a condition in."""
    return conn.execute(f"""SELECT COUNT(*) FROM results r JOIN events e ON e.id = r.event_id
                            JOIN seasons s ON s.id = e.season_id
                            WHERE r.driver_id = ? AND e.status = ? AND e.id != ?
                            AND (s.year < ? OR (s.year = ? AND e.round_number < ?)) AND {condition}""",
                        (driver_id, C.EVENT_COMPLETE, event["id"], event["year"], event["year"],
                         event["round_number"])).fetchone()[0]


def on_weekend_complete(conn, event_id, link):
    event = dict(conn.execute("""SELECT e.*, s.year FROM events e JOIN seasons s ON s.id = e.season_id
                                 WHERE e.id = ?""", (event_id,)).fetchone())
    rows = S.weekend_rows(conn, event_id)
    sid = event["season_id"]
    title = f"{event['year']} {event['name']}"
    winner = next((r for r in rows if r["race_position"] == 1 and r["result_status"] == C.STATUS_FINISHED), None)
    pole = next((r for r in rows if r["qualifying_position"] == 1), None)
    if winner:
        extra = f" from pole" if pole and pole["driver_id"] == winner["driver_id"] else \
            (f" from P{winner['qualifying_position']} on the grid" if winner["qualifying_position"] else "")
        post(conn, sid, "result", f"{winner['driver']['name']} wins the {title}{extra}",
             f"{winner['team']['name']} take 25 points in round {event['round_number']}.", link,
             winner["driver_id"], winner["team_id"])
    for r in rows:
        if not r["driver"]["is_player"]:
            continue
        name, pos, status = r["driver"]["name"], r["race_position"], r["result_status"]
        finished = status == C.STATUS_FINISHED and pos
        headline = None
        if finished and pos == 1 and not _career_before(conn, r["driver_id"], event, "r.race_position = 1 AND r.result_status = 'Finished'"):
            headline = f"Maiden victory! {name} wins for the first time"
        elif finished and pos <= 3 and not _career_before(conn, r["driver_id"], event, "r.race_position <= 3 AND r.result_status = 'Finished'"):
            headline = f"{name} scores a first career podium at the {event['name']}"
        elif finished and pos <= 10 and not _career_before(conn, r["driver_id"], event, "r.race_position <= 10 AND r.result_status = 'Finished'"):
            headline = f"First points on the board for {name}"
        elif r["qualifying_position"] == 1 and not _career_before(conn, r["driver_id"], event, "r.qualifying_position = 1"):
            headline = f"{name} takes a first career pole position"
        elif status == "DNF":
            headline = f"Heartbreak for {name}: out of the {event['name']}"
        elif finished and r["qualifying_position"] and r["qualifying_position"] - pos >= 8:
            headline = f"{name} charges from P{r['qualifying_position']} to P{pos}"
        if headline:
            post(conn, sid, "player", headline, f"{title}, round {event['round_number']}.", link, r["driver_id"], r["team_id"])
    notify(conn, None, f"Results are in: {title}" + (f", won by {winner['driver']['name']}" if winner else ""), link)


def on_window_opened(conn, window_id, link):
    window = conn.execute("SELECT * FROM market_windows WHERE id = ?", (window_id,)).fetchone()
    ref = f"window:{window_id}"
    post(conn, window["season_id"], "market", f"{window['kind']} opens: teams are shopping for {window['target_year']}",
         "Offers are going out to the player drivers.", link, ref=ref)
    for p in S.player_drivers(conn):
        n = conn.execute("SELECT COUNT(*) FROM offers WHERE window_id = ? AND driver_id = ? AND status = ?",
                         (window_id, p["id"], C.OFFER_PENDING)).fetchone()[0]
        if n:
            notify(conn, p["id"], f"{n} team{'s' if n != 1 else ''} made you an offer for {window['target_year']}", link,
                   ref=ref)


def on_signed(conn, offer, link):
    team = S.team_map(conn)[offer["team_id"]]
    driver = S.driver_map(conn)[offer["driver_id"]]
    post(conn, offer["window_season"], "market",
         f"Official: {driver['name']} signs with {team['name']}",
         f"{offer['role']}, {offer['years']} year{'s' if offer['years'] != 1 else ''} from {offer['target_year']}.",
         link, driver["id"], team["id"], ref=f"window:{offer['window_id']}")
    for p in S.player_drivers(conn):
        if p["id"] != driver["id"]:
            notify(conn, p["id"], f"{driver['name']} just signed with {team['name']}", link,
                   ref=f"window:{offer['window_id']}")


def on_talks_collapsed(conn, offer_id, link):
    offer = conn.execute("""SELECT o.*, w.season_id FROM offers o JOIN market_windows w ON w.id = o.window_id
                            WHERE o.id = ?""", (offer_id,)).fetchone()
    ref = f"window:{offer['window_id']}"
    team = S.team_map(conn)[offer["team_id"]]
    driver = S.driver_map(conn)[offer["driver_id"]]
    post(conn, offer["season_id"], "rumour", f"Paddock whispers: talks between {driver['name']} and {team['name']} break down",
         "Sources say the two sides were too far apart.", link, driver["id"], team["id"], ref=ref)


def on_new_offer(conn, driver_id, team_id, text, link):
    notify(conn, driver_id, text, link)


def on_new_season(conn, old_id, new_id, car_changes, link):
    old = S.get_season(conn, old_id)
    new = S.get_season(conn, new_id)
    table = S.driver_standings(conn, old_id)
    teams = S.constructor_standings(conn, old_id)
    if table and table[0]["points"]:
        champ = table[0]
        post(conn, old_id, "season", f"{champ['driver']['name']} is the {old['year']} World Champion",
             f"{champ['points']} points and {champ['wins']} wins.", link, champ["driver_id"],
             champ["team"]["id"] if champ["team"] else None)
    if teams and teams[0]["points"]:
        post(conn, old_id, "season", f"{teams[0]['team']['name']} win the {old['year']} Constructors' title",
             f"{teams[0]['points']} points.", link, team_id=teams[0]["team"]["id"])
    if car_changes:
        best, worst = car_changes[0], car_changes[-1]
        if best["change"] > 0:
            post(conn, new_id, "tech", f"Winter testing: {best['team']['name']} find big gains ({best['change']:+.1f})",
                 f"Their car is rated {best['rating']:.1f} heading into {new['year']}.", link, team_id=best["team"]["id"])
        if worst["change"] < 0:
            post(conn, new_id, "tech", f"Trouble at {worst['team']['name']}: new car is off the pace ({worst['change']:+.1f})",
                 f"Rated {worst['rating']:.1f} for {new['year']}.", link, team_id=worst["team"]["id"])
    notify(conn, None, f"The {new['year']} season has begun", link)


# --------------------------------------------------------------------------- race results email

def results_email(conn, event_id, url):
    """Subject, plain text and HTML for the post-race email."""
    from html import escape
    event = dict(conn.execute("""SELECT e.*, s.year FROM events e JOIN seasons s ON s.id = e.season_id
                                 WHERE e.id = ?""", (event_id,)).fetchone())
    rows = S.weekend_rows(conn, event_id)
    title = f"{event['year']} {event['name']}"
    classified = sorted((r for r in rows if r["race_position"]), key=lambda r: r["race_position"])

    def fin(r):
        return f"P{r['race_position']}" if r["result_status"] == C.STATUS_FINISHED and r["race_position"] else r["result_status"]

    top = classified[:10]
    players = [r for r in rows if r["driver"]["is_player"]]
    table = S.driver_standings(conn, event["season_id"])
    board = table[:5] + [r for r in table[5:] if r["driver"]["is_player"]]

    lines = [f"{title}: round {event['round_number']} results", ""]
    lines += [f"{fin(r):>4}  {r['driver']['name']} ({r['team']['name']})  +{r['gp_points'] + r['sprint_pts']}" for r in top]
    if players:
        lines += ["", "Your weekends:"]
        for r in players:
            q = f"Q P{r['qualifying_position']}" if r["qualifying_position"] else "Q —"
            lines.append(f"  {r['driver']['name']}: {q} → {fin(r)}, {r['gp_points'] + r['sprint_pts']} pts")
    lines += ["", "Championship:"] + [f"  {r['position']}. {r['driver']['name']} {r['points']}" for r in board]
    lines += ["", f"Full results: {url}", "", "You get these because race-result emails are on in your account. "
              "Turn them off in Accounts."]

    def row_html(r, extra=""):
        return (f"<tr><td style='padding:4px 8px;font-weight:700'>{escape(fin(r))}</td>"
                f"<td style='padding:4px 8px;border-left:3px solid {escape(r['team']['color'])}'>{escape(r['driver']['name'])}"
                f"<br><small style='color:#8d97a8'>{escape(r['team']['name'])}</small></td>"
                f"<td style='padding:4px 8px;text-align:right'>{extra}</td></tr>")
    html = [f"<div style='font-family:Segoe UI,Arial,sans-serif;background:#0c1019;color:#e8ecf3;padding:20px'>",
            f"<div style='color:#e10600;font-size:12px;letter-spacing:2px;text-transform:uppercase'>Round {event['round_number']}</div>",
            f"<h1 style='margin:4px 0 16px'>{escape(title)}</h1><table style='border-collapse:collapse;width:100%;max-width:560px'>"]
    html += [row_html(r, f"+{r['gp_points'] + r['sprint_pts']}") for r in top]
    html.append("</table>")
    if players:
        html.append("<h2 style='font-size:16px;margin:20px 0 8px'>Your weekends</h2><ul>")
        for r in players:
            q = f"P{r['qualifying_position']}" if r["qualifying_position"] else "—"
            html.append(f"<li><b>{escape(r['driver']['name'])}</b>: qualified {q}, finished {escape(fin(r))}, "
                        f"{r['gp_points'] + r['sprint_pts']} pts</li>")
        html.append("</ul>")
    html.append("<h2 style='font-size:16px;margin:20px 0 8px'>Championship</h2><ol style='padding-left:20px'>")
    html += [f"<li value='{r['position']}'>{escape(r['driver']['name'])}: <b>{r['points']}</b></li>" for r in board]
    html.append(f"</ol><p><a href='{escape(url)}' style='color:#ff5a4f'>Open the full results →</a></p>"
                "<p style='color:#8d97a8;font-size:12px'>Turn these emails off in Accounts.</p></div>")
    return f"🏁 {title}: results are in", "\n".join(lines), "".join(html)
