"""Auth against a live Postgres: the login that writes a row, and the scoping it buys.

`test_auth.py` covers the signature and the handshake with no database. What needs one is
the part of the callback that decides *which user* the cookie names — including the case
this project will hit exactly once, when the first real login has to inherit the evidence
written back when there was no login at all.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from conftest import TEST_SESSION_SECRET, auth_settings, sign_in
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.auth import SESSION_COOKIE, GitHubOAuth, get_github, sign
from api.db import get_engine
from api.main import app
from api.models import User
from api.settings import Settings, get_settings
from api.users import LOCAL_GITHUB_ID, single_user, user_for_github_id

pytestmark = pytest.mark.db

REAL_GITHUB_ID = 90210


class FakeGitHub(GitHubOAuth):
    def __init__(self, account: int) -> None:
        self.account = account

    def exchange_code(self, **_: Any) -> str:
        return "an-access-token"

    def account_id(self, access_token: str) -> int:
        return self.account


def oauth_settings() -> Settings:
    """Takes no arguments on purpose. FastAPI reads an override's signature, so a
    `**overrides` parameter would become a required query parameter and every route would
    answer 400 — which is exactly how the first draft of this file failed."""
    return auth_settings().model_copy(
        update={
            "github_client_id": "client-id",
            "github_client_secret": "client-secret",
            "github_allowed_id": REAL_GITHUB_ID,
            "github_redirect_uri": "http://localhost:8000/auth/callback",
        }
    )


@pytest.fixture
def restore_github_id():
    """These tests rewrite the single user's `github_id`, which is the one column a login
    mutates. Put it back, or every later test signs in as somebody the fixtures do not
    expect."""
    with Session(get_engine()) as db:
        original = single_user(db).github_id
    yield
    with Session(get_engine()) as db:
        user = single_user(db)
        user.github_id = original
        db.add(user)
        db.commit()


def complete_login(client: TestClient, account: int, **kwargs: Any) -> Any:
    """Drive /auth/login then /auth/callback, the way a browser would.

    Puts the single user row back into the state a database predating auth was in first,
    unless some row already carries `account` — so the login *adopts* rather than creating.

    That setup used to live in the one test about adoption, and every other test here
    depended on running after it. `restore_github_id` puts the real id back when each test
    finishes, so the next login found no pre-auth row and correctly created a **second
    user** — correct behaviour, and fatal to a suite whose fixtures assume one. It stayed
    invisible while this machine's row happened to still be pre-auth, and surfaced the hour
    a real GitHub login set a real id on it.
    """
    with Session(get_engine()) as db:
        if db.exec(select(User).where(User.github_id == account)).first() is None:
            user = single_user(db)
            user.github_id = LOCAL_GITHUB_ID
            db.add(user)
            db.commit()

    app.dependency_overrides[get_settings] = oauth_settings
    app.dependency_overrides[get_github] = lambda: FakeGitHub(account)
    location = client.get("/auth/login", follow_redirects=False).headers["location"]
    state = location.split("state=")[1].split("&")[0]
    return client.get(f"/auth/callback?code=the-code&state={state}", **kwargs)


def test_the_first_login_adopts_the_pre_auth_user(restore_github_id):
    """The row written before auth existed carries every `concept_evidence` row this
    project has. A login that created a second user would strand all of it behind an
    account nobody can sign in as."""
    with Session(get_engine()) as db:
        user = single_user(db)
        user.github_id = LOCAL_GITHUB_ID  # as a database predating auth
        db.add(user)
        db.commit()
        before = user.id

    resp = complete_login(TestClient(app), REAL_GITHUB_ID)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"authenticated": True, "user_id": before, "github_id": REAL_GITHUB_ID}

    with Session(get_engine()) as db:
        assert db.get(User, before).github_id == REAL_GITHUB_ID
        assert len(db.exec(select(User)).all()) == 1


def test_a_browser_completing_a_login_is_sent_to_the_app(restore_github_id):
    """A browser gets a 303 home; anything else still gets the JSON body.

    The callback answered JSON unconditionally, "because there is no web app to redirect
    to until Phase 5". Phase 5 landed and the premise expired, leaving a browser that had
    just signed in looking at a JSON document with no way back to the app.

    The redirect is relative on purpose: it resolves against whichever origin served the
    request, which is necessarily the origin the cookie was just set on. Sending the user
    to an absolute host would need a second setting that could disagree with
    `GITHUB_REDIRECT_URI` about where home is.
    """
    client = TestClient(app)
    browser = complete_login(
        client,
        REAL_GITHUB_ID,
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )

    assert browser.status_code == 303
    assert browser.headers["location"] == "/"
    # The cookie still has to be set — a redirect that forgot it would loop.
    assert "ih_session" in browser.headers.get("set-cookie", "")
    assert client.get("/auth/me").status_code == 200


def test_logging_in_twice_does_not_create_a_second_user(restore_github_id):
    client = TestClient(app)
    first = complete_login(client, REAL_GITHUB_ID).json()["user_id"]
    second = complete_login(TestClient(app), REAL_GITHUB_ID).json()["user_id"]
    assert first == second
    with Session(get_engine()) as db:
        assert len(db.exec(select(User)).all()) == 1


def test_the_callback_sets_a_cookie_that_the_api_accepts(restore_github_id):
    client = TestClient(app)
    resp = complete_login(client, REAL_GITHUB_ID)
    assert SESSION_COOKIE in resp.cookies

    # Same client, so it carries the cookie the callback just set. The settings override
    # is the OAuth one, whose secret is still the test secret, so the API can verify it.
    assert client.get("/auth/me").status_code == 200
    assert client.get("/api/v1/mastery").status_code == 200


def test_a_second_account_does_not_take_over_the_first_users_row(restore_github_id):
    """The configured account changing is not the same event as the same person logging in
    again, and the schema is happy to hold both. It is logged, and the newcomer starts with
    an empty projection rather than inheriting a history that is not theirs."""
    with Session(get_engine()) as db:
        original = single_user(db)
        original.github_id = REAL_GITHUB_ID
        db.add(original)
        db.commit()
        original_id = original.id

    with Session(get_engine()) as db:
        newcomer = user_for_github_id(db, REAL_GITHUB_ID + 1)
        assert newcomer.id != original_id
        db.delete(newcomer)
        db.commit()


def test_one_users_session_is_not_readable_by_another(created_sessions):
    """Multi-tenancy is out of scope (docs/ARCHITECTURE.md) and this is not that: it is the
    session queries being scoped to the caller the way every mastery query already is. A
    stranger's id answers 404, the same as a made-up one, so the reply says nothing about
    whether the session exists."""
    owner = sign_in(TestClient(app))
    created = owner.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 45})
    session_id = created.json()["id"]
    created_sessions.append(session_id)

    stranger = sign_in(TestClient(app), "01STRANGERSTRANGERSTRANG")
    assert stranger.get(f"/api/v1/sessions/{session_id}").status_code == 404
    assert stranger.get(f"/api/v1/sessions/{session_id}/report").status_code == 404
    assert stranger.post(f"/api/v1/sessions/{session_id}/end").status_code == 404
    assert stranger.get("/api/v1/sessions").json()["sessions"] == []
    # And the owner still sees it, so the assertions above are about ownership rather than
    # about the session having failed to be created.
    assert owner.get(f"/api/v1/sessions/{session_id}").status_code == 200
    assert session_id in [row["id"] for row in owner.get("/api/v1/sessions").json()["sessions"]]


def test_a_cookie_minted_by_the_cli_is_the_one_the_api_accepts():
    """`make login` is the only way to a session that does not go through GitHub, so what
    it prints has to be a cookie this API would accept."""
    from api import mint_session

    app.dependency_overrides[get_settings] = auth_settings
    with Session(get_engine()) as db:
        user = single_user(db)
        expected_id = user.id

    minted = mint_session.session_token(
        user_id=expected_id, github_id=LOCAL_GITHUB_ID, secret=TEST_SESSION_SECRET
    )
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, minted)
    assert client.get("/auth/me").json()["user_id"] == expected_id


def test_an_expired_cookie_stops_working():
    """Belt and braces on the one property a signed cookie has to have: the signature is
    still valid, and the session is not."""
    app.dependency_overrides[get_settings] = auth_settings
    with Session(get_engine()) as db:
        user_id = single_user(db).id
    stale = sign(
        {"uid": user_id, "gid": LOCAL_GITHUB_ID, "iat": 0, "exp": int(time.time()) - 1},
        TEST_SESSION_SECRET,
    )
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, stale)
    assert client.get("/api/v1/mastery").status_code == 401
