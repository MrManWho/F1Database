"""Local development server for Paddock Legacy (Windows: double-click dev.bat). Never used by Render.

    python dev.py                 start the site on http://127.0.0.1:5050 with live reload
    python dev.py seed LOGIN      add the fictional 8-round test league, with LOGIN as Race Master
    python dev.py finale LOGIN    add the fictional league with only its last round left
    python dev.py reset           set the local data aside (renamed, never deleted) and start empty next time
    python dev.py where           show which folders this copy reads and writes, then stop

Everything stays on this computer:
  * data (accounts.db, every league file, backups, avatars, imports) lives in .devdata/ inside this folder, never in
    the desktop app's folder (%LOCALAPPDATA%\\F1UniverseTracker) or the live site's /data disk;
  * F1_TRACKER_TEST_SITE=1 is switched on, so nothing is ever sent: emails, Discord posts and phone alerts are saved
    as delivery previews (Account -> Settings -> Delivery preview), including anything left in an imported outbox;
  * the server only listens on this computer (127.0.0.1).
It refuses to start if anything points somewhere else (see check()).

Live reload: Python changes restart the server, template changes show on the next page load, and the open browser
tab refreshes itself when a template, stylesheet or script changes. Stylesheets are swapped in place; if you have
typed into a form, the page is not reloaded and a small "Reload" bar appears instead, so nothing typed is lost.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEV_DATA = ROOT / ".devdata"
HOST = "127.0.0.1"
PORT = int(os.environ.get("F1_DEV_PORT", "5050"))
WATCH = [ROOT / "templates", ROOT / "static"]
SKIP = ("vendor",)                                 # the OCR engine files: large and never edited
# Settings that would connect this copy to a real mail server, the live disk or the host.
OUTSIDE = ["RENDER", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "F1_TRACKER_BACKUP_PASSPHRASE"]


def environment():
    """Set the variables this copy runs with. Called before anything from f1tracker is imported."""
    os.environ.setdefault("F1_TRACKER_DATA_DIR", str(DEV_DATA))
    os.environ["F1_TRACKER_ENV"] = "local"
    os.environ["F1_TRACKER_TEST_SITE"] = "1"       # the test site's "never send anything" switch
    os.environ["F1_TRACKER_SECURE_COOKIES"] = "0"  # plain http on this computer


def check():
    """Refuse an unsafe configuration. Returns a list of problems (empty: safe)."""
    problems = []
    if sys.version_info[:2] != (3, 11):
        problems.append(f"Python {sys.version.split()[0]} is running; this project needs 3.11 (the live site's "
                        "version: calculations differ slightly on 3.12+). Start it with dev.bat.")
    for name in OUTSIDE:
        if os.environ.get(name):
            problems.append(f"{name} is set in this window. Local development must not use it: close this "
                            "window and open a new one without it.")
    data = Path(os.environ["F1_TRACKER_DATA_DIR"]).resolve()
    forbidden = [Path("/data").resolve(), (Path.home() / ".f1-universe-tracker").resolve()]
    if os.environ.get("LOCALAPPDATA"):
        forbidden.append((Path(os.environ["LOCALAPPDATA"]) / "F1UniverseTracker").resolve())
    if data in forbidden:
        problems.append(f"The data folder is {data}, which belongs to the desktop app or the live site.")
    elif ROOT not in data.parents:
        problems.append(f"The data folder {data} is outside this project folder. Unset F1_TRACKER_DATA_DIR "
                        "(local data belongs in .devdata).")
    return problems


def where():
    from f1tracker import ops, storage, testsite
    base = storage.data_dir()
    print(f"  Environment:  {ops.environment_label()}   (sending: {'blocked, saved as previews' if testsite.on() else 'ON'})")
    print(f"  Data folder:  {base}")
    print(f"    accounts:   {base / 'accounts.db'}")
    print(f"    leagues:    {storage.careers_dir()}  ({len(list(storage.careers_dir().glob('*' + storage.CAREER_EXT)))} files)")
    print(f"    backups:    {storage.backups_dir()}")
    print(f"    avatars, imports, readiness reports: inside the data folder")


# --------------------------------------------------------------------------- live reload (development only)

def _stamp():
    """The newest change time under templates/ and static/, and whether it was a stylesheet."""
    newest, kind = 0.0, "page"
    for folder in WATCH:
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            for name in filenames:
                try:
                    t = os.stat(os.path.join(dirpath, name)).st_mtime
                except OSError:
                    continue
                if t > newest:
                    newest, kind = t, ("css" if name.endswith(".css") else "page")
    return newest, kind


LIVE_JS = """(function () {
  var dirty = false, boot = null, bar = null;
  document.addEventListener("input", function (e) { if (e.target.form) dirty = true; }, true);
  document.addEventListener("submit", function () { dirty = false; }, true);
  function offer() {
    if (bar) return;
    bar = document.createElement("div");
    bar.setAttribute("style", "position:fixed;left:12px;bottom:12px;z-index:99999;background:#0b1730;color:#fff;" +
      "font:14px sans-serif;padding:10px 14px;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.3)");
    bar.innerHTML = "Files changed. Your typing is kept until you <button style='margin-left:6px'>Reload</button>";
    bar.querySelector("button").onclick = function () { location.reload(); };
    document.body.appendChild(bar);
  }
  function reload() { if (dirty) offer(); else location.reload(); }
  function swapCss() {
    var links = document.querySelectorAll("link[rel=stylesheet]");
    for (var i = 0; i < links.length; i++) {
      var u = new URL(links[i].href); u.searchParams.set("lr", Date.now()); links[i].href = u.toString();
    }
  }
  var es = new EventSource("/__dev/events");
  es.onmessage = function (m) {
    var d = JSON.parse(m.data);
    if (boot === null) { boot = d.boot; return; }
    if (d.boot !== boot) return reload();          // the server restarted after a Python change
    if (d.kind === "css") swapCss(); else reload();
  };
})();"""


def add_live_reload(app):
    from flask import Response, request
    boot = str(time.time())

    def livereload_js():
        return Response(LIVE_JS, mimetype="application/javascript", headers={"Cache-Control": "no-store"})

    def events():
        def stream():
            last, _ = _stamp()
            yield "data: " + json.dumps({"boot": boot}) + "\n\n"
            while True:
                time.sleep(0.5)
                now, kind = _stamp()
                if now != last:
                    last = now
                    yield "data: " + json.dumps({"boot": boot, "kind": kind}) + "\n\n"
                else:
                    yield ": keep-alive\n\n"
        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-store"})

    def dev_paths():
        """Answer the two /__dev/ addresses before the site's own checks (sign-in, setup, maintenance) run."""
        if request.path == "/__dev/livereload.js":
            return livereload_js()
        if request.path == "/__dev/events":
            return events()
        return None
    app.before_request_funcs.setdefault(None, []).insert(0, dev_paths)

    @app.after_request
    def dev_inject(response):
        if (response.mimetype == "text/html" and response.status_code == 200 and not response.direct_passthrough
                and not request.path.startswith("/__dev/")):
            body = response.get_data(as_text=True)
            if "</body>" in body:
                body = body.replace("</body>", '<script src="/__dev/livereload.js"></script></body>', 1)
                response.set_data(body)
        return response


# --------------------------------------------------------------------------- commands

def serve():
    from f1tracker.app import create_app
    from f1tracker.constants import APP_NAME, APP_VERSION
    app = create_app({"TEMPLATES_AUTO_RELOAD": True, "STATIC_FINGERPRINT_FRESH": True,
                      "SESSION_COOKIE_SECURE": False})
    add_live_reload(app)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":      # print once, not again after each restart
        print(f"\n  {APP_NAME} v{APP_VERSION}: LOCAL DEVELOPMENT")
        where()
        print(f"\n  Open:  http://{HOST}:{PORT}")
        print("  Stop:  press Ctrl+C in this window\n")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=True, threaded=True)


def account_exists(login):
    from f1tracker import auth
    if auth.get_user(login):
        return True
    print(f"No account called {login!r} here yet. Create it in the browser first (the first account becomes the "
          "site owner), then run this again. Nothing was added.")
    return False


def main(argv):
    environment()
    problems = check()
    if problems:
        print("\nLocal development will not start:\n")
        for p in problems:
            print("  - " + p)
        print()
        return 1
    cmd = argv[1] if len(argv) > 1 else "serve"
    if cmd == "serve":
        serve()
        return 0
    if cmd == "where":
        where()
        return 0
    if cmd == "seed" and len(argv) == 3:
        if not account_exists(argv[2]):
            return 1
        from f1tracker import roles, services as S, storage, testsite
        token = testsite.seed()
        with storage.session(token) as conn:
            roles.set_member(conn, argv[2], "race_master", S.player_drivers(conn)[0]["id"])
        print(f"Added the fictional 8-round league ({token}) with {argv[2]} as Race Master driving Player One.")
        return 0
    if cmd == "finale" and len(argv) == 3:
        if not account_exists(argv[2]):
            return 1
        from f1tracker import testsite
        token = testsite.seed_final_round(argv[2])
        print(f"Added the fictional last-round league ({token}) with {argv[2]} as Race Master driving Player One.")
        return 0
    if cmd == "reset":
        data = Path(os.environ["F1_TRACKER_DATA_DIR"])
        if not data.exists():
            print("There is no local data yet.")
            return 0
        if input(f"Set aside everything in {data}? The site starts empty next time. Type RESET: ").strip() != "RESET":
            print("Nothing was changed.")
            return 1
        kept = data.with_name(data.name + "-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        data.rename(kept)
        print(f"Moved to {kept}. Delete that folder yourself once you're sure you don't need it.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
