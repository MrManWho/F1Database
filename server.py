"""Production entry point for hosting the tracker on a website (Render, Railway, Fly.io, a VPS...).

Reads PORT from the environment, listens on all interfaces, trusts the host's HTTPS proxy and marks
cookies secure. Keep F1_TRACKER_DATA_DIR on a persistent disk so careers survive redeploys.
"""

import os

from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

from f1tracker.app import create_app
from f1tracker.constants import APP_NAME, APP_VERSION
from f1tracker.storage import data_dir

app = create_app({"SESSION_COOKIE_SECURE": os.environ.get("F1_TRACKER_SECURE_COOKIES", "1") == "1"})
# The host terminates HTTPS and forwards the real client address (used by the login lockout).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"{APP_NAME} v{APP_VERSION} on port {port}, data in {data_dir()}", flush=True)
    serve(app, host="0.0.0.0", port=port, threads=8)
