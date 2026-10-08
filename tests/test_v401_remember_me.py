"""4.0.1: "Remember me" on the sign-in page keeps the sign-in cookie after the browser closes."""
from f1tracker import auth
from f1tracker.app import create_app


def _client():
    app = create_app({"TESTING": True, "CSRF_ENABLED": False})
    auth.create_user("racer", "Racer", "longpassword123", is_master=True)
    return app.test_client()


def _cookie(resp):
    return next(h for h in resp.headers.getlist("Set-Cookie") if h.startswith("session="))


def test_sign_in_page_offers_remember_me():
    c = _client()
    assert 'name="remember"' in c.get("/login").get_data(as_text=True)


def test_remember_me_keeps_the_cookie():
    c = _client()
    r = c.post("/login", data={"username": "racer", "password": "longpassword123", "remember": "1"})
    assert r.status_code == 302 and "Expires=" in _cookie(r)
    assert c.get("/").status_code == 200


def test_without_remember_me_the_cookie_ends_with_the_browser():
    c = _client()
    r = c.post("/login", data={"username": "racer", "password": "longpassword123"})
    assert r.status_code == 302 and "Expires=" not in _cookie(r)
