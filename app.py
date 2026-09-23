"""WSGI entry point: `python app.py` runs the Flask dev server; use launcher.py for normal play."""

from f1tracker.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
