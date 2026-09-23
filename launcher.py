"""Start the tracker with Waitress and open it in the default browser.

By default it only listens on this computer (127.0.0.1). Run with --lan (or run_lan.bat) so the
other player can log in from another device on the same home network.
"""

import os
import socket
import sys
import threading
import webbrowser

from waitress import serve

from f1tracker.app import create_app
from f1tracker.constants import APP_NAME, APP_VERSION
from f1tracker.storage import data_dir

PREFERRED_PORT = 8765


def port_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(host):
    if port_free(host, PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except OSError:
        return None


def main():
    lan = "--lan" in sys.argv or os.environ.get("F1_TRACKER_LAN") == "1"
    host = "0.0.0.0" if lan else "127.0.0.1"
    port = pick_port(host)
    local_url = f"http://127.0.0.1:{port}"
    print(f"{APP_NAME} v{APP_VERSION}")
    print(f"Saves: {data_dir()}")
    print(f"Open:  {local_url}")
    if lan:
        ip = lan_address()
        if ip:
            print(f"Other player on your network: http://{ip}:{port}")
        print("LAN mode: anyone on your network can reach the login page. Use strong passwords.")
    print("Keep this window open while you play. Closing it stops the tracker (your saves are safe).")
    threading.Timer(1.0, lambda: webbrowser.open(local_url)).start()
    serve(create_app(), host=host, port=port, threads=6)


if __name__ == "__main__":
    main()
