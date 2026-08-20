"""Auth without a database: the signature, the refusals, and the OAuth handshake.

The one test here worth reading twice is `test_every_api_route_requires_a_session`. The
others check behaviour that was written on purpose; that one checks a property no author
can maintain by attention — that nothing under `/api/v1` is reachable without a cookie,
including a route added six months from now by someone who never read this file.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    GitHubOAuth,
    get_github,
    session_token,
    sign,
    verify,
)
from api.main import app
from api.settings import Settings, get_settings

SECRET = "test-secret-not-a-real-one"
ALLOWED_GITHUB_ID = 4242


def make_settings(**overrides: Any) -> Settings:
    base = {
        "session_secret": SECRET,
        "github_client_id": "client-id",
        "github_client_secret": "client-secret",
        "github_allowed_id": ALLOWED_GITHUB_ID,
        "cookie_secure": False,
        "github_redirect_uri": "http://localhost:8000/auth/callback",
    }
    return Settings(**(base | overrides))


@pytest.fixture(autouse=True)
def _configured():
    """Every test starts from a fully configured server; the ones about missing
    configuration override it themselves."""
    # A zero-argument callable, not `make_settings` itself: FastAPI reads the override's
    # signature, and a `**overrides` parameter becomes a required query parameter named
    # `overrides` — every route then answers 400 instead of anything about auth.
    app.dependency_overrides[get_settings] = lambda: make_settings()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def cookie_for(user_id: str = "01USER", github_id: int = ALLOWED_GITHUB_ID) -> dict[str, str]:
    return {SESSION_COOKIE: session_token(user_id=user_id, github_id=github_id, secret=SECRET)}


# --- The signature --------------------------------------------------------------------


def test_a_signed_payload_round_trips():
    token = sign({"uid": "01USER", "exp": time.time() + 60}, SECRET)
    assert verify(token, SECRET) == {"uid": "01USER", "exp": pytest.approx(time.time() + 60, abs=2)}


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda t: t[:-1] + ("a" if t[-1] != "a" else "b"), id="signature flipped"),
        pytest.param(lambda t: t.split(".")[0] + ".", id="signature stripped"),
        pytest.param(lambda t: t.replace(".", "", 1), id="separator removed"),
        pytest.param(lambda t: "", id="empty"),
        pytest.param(lambda t: "garbage", id="not a token"),
    ],
)
def test_a_tampered_token_is_not_a_session(mutate):
    token = mutate(session_token(user_id="01USER", github_id=1, secret=SECRET))
    assert verify(token, SECRET) is None


def test_another_servers_secret_does_not_verify():
    token = session_token(user_id="01USER", github_id=1, secret="a different secret")
    assert verify(token, SECRET) is None


def test_an_expired_token_is_not_a_session():
    long_ago = time.time() - 2 * 365 * 24 * 3600
    token = session_token(user_id="01USER", github_id=1, secret=SECRET, issued=long_ago)
    assert verify(token, SECRET) is None
    # And the same token was valid when it was issued, so the test above is about expiry
    # rather than about anything else being wrong with it.
    assert verify(token, SECRET, now=long_ago + 60) is not None


def test_a_payload_that_is_not_an_object_is_rejected():
    """`json.loads` is happy to return a list. Signed by us and still not a session."""
    assert verify(sign(["not", "a", "session"], SECRET), SECRET) is None  # type: ignore[arg-type]


def test_a_signed_token_with_no_expiry_is_rejected():
    assert verify(sign({"uid": "01USER"}, SECRET), SECRET) is None


# --- What the routes do with it ---------------------------------------------------------


def test_health_needs_no_session(client):
    assert client.get("/health").status_code == 200


def test_an_api_route_without_a_cookie_is_401_problem_json(client):
    resp = client.get("/api/v1/corpus/status")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"].endswith("/unauthenticated")
    assert body["instance"] == "/api/v1/corpus/status"


def test_a_valid_cookie_gets_through(client):
    resp = client.get("/api/v1/corpus/status", cookies=cookie_for())
    assert resp.status_code == 200
    assert resp.json()["concepts"] > 50


def test_a_cookie_signed_with_another_secret_is_401(client):
    forged = session_token(user_id="01USER", github_id=1, secret="not the server's secret")
    resp = client.get("/api/v1/corpus/status", cookies={SESSION_COOKIE: forged})
    assert resp.status_code == 401


def test_a_session_payload_missing_its_fields_is_401(client):
    """Signed by this server and still not a session — only a bug can produce it, and it
    fails closed rather than guessing what the payload meant."""
    token = sign({"exp": time.time() + 60}, SECRET)
    resp = client.get("/api/v1/corpus/status", cookies={SESSION_COOKIE: token})
    assert resp.status_code == 401


def test_without_a_session_secret_the_api_is_503_not_401(client):
    """A 401 would send an operator looking for a login problem. The server is the one
    that is misconfigured, and the message names the variable."""
    app.dependency_overrides[get_settings] = lambda: make_settings(session_secret=None)
    resp = client.get("/api/v1/corpus/status")
    assert resp.status_code == 503
    assert resp.json()["type"].endswith("/not-configured")
    assert "SESSION_SECRET" in resp.json()["detail"]


ROUTE_ARGUMENTS = {"session_id": "01SESSION", "concept_id": "sliding-window"}


def test_every_api_route_requires_a_session(client):
    """Not one route at a time: the whole surface, from the schema the app generates.

    The guard is a dependency on the `/api/v1` router, so this passes by construction —
    which is the point. It fails the day someone mounts a route outside that router, or
    moves the dependency onto individual routes and misses one.
    """
    paths = client.get("/openapi.json").json()["paths"]
    api_routes = [
        (method.upper(), path)
        for path, ops in paths.items()
        for method in ops
        if path.startswith("/api/v1")
    ]
    assert len(api_routes) >= 10, "the surface shrank; this test would pass vacuously"

    open_routes = []
    for method, path in api_routes:
        url = path
        for name, value in ROUTE_ARGUMENTS.items():
            url = url.replace(f"{{{name}}}", value)
        resp = client.request(method, url, json={})
        if resp.status_code != 401:
            open_routes.append((method, path, resp.status_code))
    assert not open_routes, f"reachable without a session: {open_routes}"


# --- The OAuth handshake ------------------------------------------------------------------


class FakeGitHub(GitHubOAuth):
    """The two calls, without the network. Subclasses the real class so a change to its
    interface breaks this instead of quietly diverging from it."""

    def __init__(self, account: int, *, code: str = "the-code") -> None:
        self.account = account
        self.expected_code = code
        self.exchanged: list[str] = []

    def exchange_code(
        self, *, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> str:
        self.exchanged.append(code)
        assert code == self.expected_code
        return "an-access-token"

    def account_id(self, access_token: str) -> int:
        assert access_token == "an-access-token"
        return self.account


def test_login_redirects_to_github_with_a_state_cookie(client):
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 302
    location = httpx.URL(resp.headers["location"])
    assert str(location).startswith("https://github.com/login/oauth/authorize")
    assert location.params["client_id"] == "client-id"
    assert location.params["scope"] == "read:user"
    # The state is both signed and echoed in a cookie: the signature proves we issued it,
    # the cookie proves this browser is the one that started the flow.
    state = location.params["state"]
    assert verify(state, SECRET) is not None
    assert client.cookies[STATE_COOKIE] == state


def test_login_without_oauth_configured_is_503(client):
    app.dependency_overrides[get_settings] = lambda: make_settings(github_client_id=None)
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 503
    assert "GITHUB_CLIENT_ID" in resp.json()["detail"]


def test_an_allowed_id_of_zero_is_treated_as_unset(client):
    """Zero is `api.users`' pre-auth sentinel, no GitHub account has it, and honouring it
    would mean an allowed account nobody can be."""
    app.dependency_overrides[get_settings] = lambda: make_settings(github_allowed_id=0)
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 503
    assert "GITHUB_ALLOWED_ID" in resp.json()["detail"]


def test_a_callback_without_the_state_cookie_is_refused(client):
    """Login-CSRF: an attacker who holds a valid state from their own login must not be
    able to complete it in someone else's browser."""
    app.dependency_overrides[get_github] = lambda: FakeGitHub(ALLOWED_GITHUB_ID)
    state = sign({"n": "nonce", "exp": time.time() + 60}, SECRET)
    resp = client.get(f"/auth/callback?code=the-code&state={state}")
    assert resp.status_code == 400
    assert resp.json()["type"].endswith("/oauth-state-mismatch")


def test_a_callback_whose_state_was_not_signed_here_is_refused(client):
    forged = sign({"n": "nonce", "exp": time.time() + 60}, "another secret")
    client.cookies.set(STATE_COOKIE, forged)
    resp = client.get(f"/auth/callback?code=the-code&state={forged}")
    assert resp.status_code == 400


def test_another_github_account_is_403(client):
    """The account check is the whole of the access control: OAuth proves who you are, and
    this is what says that is not who this deployment serves."""
    app.dependency_overrides[get_github] = lambda: FakeGitHub(ALLOWED_GITHUB_ID + 1)
    state = client.get("/auth/login", follow_redirects=False).headers["location"].split("state=")[1]
    state = state.split("&")[0]
    resp = client.get(f"/auth/callback?code=the-code&state={state}")
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/forbidden-account")
    assert SESSION_COOKIE not in resp.cookies


def test_me_reports_the_principal(client):
    resp = client.get("/auth/me", cookies=cookie_for(user_id="01WHOEVER"))
    assert resp.status_code == 200
    assert resp.json() == {
        "authenticated": True,
        "user_id": "01WHOEVER",
        "github_id": ALLOWED_GITHUB_ID,
    }


def test_me_without_a_cookie_is_401(client):
    assert client.get("/auth/me").status_code == 401


def test_logout_clears_the_cookie(client):
    """Asserted on the header rather than on the client's jar: a cookie `client.cookies.set`
    stored with no domain is not the one a `Set-Cookie` for `testserver` replaces, so the
    jar keeps it and the assertion would be about httpx, not about logout."""
    client.cookies.set(SESSION_COOKIE, session_token(user_id="01USER", github_id=1, secret=SECRET))
    resp = client.post("/auth/logout")
    assert resp.status_code == 204
    cleared = resp.headers["set-cookie"]
    assert cleared.startswith(f'{SESSION_COOKIE}=""')
    assert "Max-Age=0" in cleared
    assert "Path=/" in cleared
