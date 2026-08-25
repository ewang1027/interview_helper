"""The two command-line entry points.

Neither had a test, and both are things a person runs when something is already wrong —
`make login` when they cannot get in, `make cost-report` when they want to know what a
session cost. A CLI that fails at the moment it is reached for is worse than one that does
not exist, because reaching for it was the recovery.
"""

from __future__ import annotations

import pytest
from conftest import use_settings
from sqlmodel import Session, delete, select

from api import cost_report, mint_session
from api.auth import SESSION_COOKIE, verify
from api.db import get_engine
from api.models import LlmCall
from api.users import single_user

pytestmark = pytest.mark.db


@pytest.fixture
def no_ledger():
    """`cost_report` promises zeros on an empty table, which needs an empty table."""
    with Session(get_engine()) as db:
        kept = list(db.exec(select(LlmCall)).all())
        db.exec(delete(LlmCall))
        db.commit()
    yield
    with Session(get_engine()) as db:
        for row in kept:
            db.merge(row)
        db.commit()


# --- mint_session -----------------------------------------------------------------------


def test_a_minted_token_verifies_with_the_servers_own_secret(capsys, monkeypatch):
    """The whole point: this grants nothing that holding SESSION_SECRET did not already
    grant, because it signs with the same secret the server verifies with."""
    settings = use_settings(session_secret="a-secret-for-this-test-only-0000000000")
    monkeypatch.setattr(mint_session, "get_settings", lambda: settings)

    assert mint_session.main(["--raw"]) == 0
    token = capsys.readouterr().out.strip()

    payload = verify(token, settings.session_secret)
    assert payload is not None
    with Session(get_engine()) as db:
        assert payload["uid"] == single_user(db).id


def test_the_default_output_is_something_you_can_paste(capsys, monkeypatch):
    settings = use_settings(session_secret="a-secret-for-this-test-only-0000000000")
    monkeypatch.setattr(mint_session, "get_settings", lambda: settings)

    assert mint_session.main([]) == 0
    out = capsys.readouterr().out
    assert f"export IH_COOKIE='{SESSION_COOKIE}=" in out
    assert "curl" in out
    # The expiry is stated, because a cookie that stopped working silently is the thing
    # somebody running this is usually trying to diagnose.
    assert "valid until" in out


def test_no_secret_is_a_failure_that_says_how_to_fix_it(capsys, monkeypatch):
    """Exit 1 and an instruction, not a traceback: this runs when someone is already
    stuck, and `make login` swallowing a stack trace would be the second problem."""
    monkeypatch.setattr(mint_session, "get_settings", lambda: use_settings(session_secret=None))

    assert mint_session.main([]) == 1
    captured = capsys.readouterr()
    assert "SESSION_SECRET is not set" in captured.err
    assert "secrets.token_urlsafe" in captured.err
    assert captured.out == ""


# --- cost_report ------------------------------------------------------------------------


def test_the_report_prints_zeros_on_an_empty_ledger(capsys, no_ledger):
    """Documented behaviour: no session has run in this repo's history, so the common case
    is an empty table and it must not be an error."""
    cost_report.main()
    out = capsys.readouterr().out
    assert "calls: 0" in out
    assert "total cost: $0.0000" in out


def test_the_report_totals_and_splits_by_job(capsys, no_ledger):
    with Session(get_engine()) as db:
        for job, cost in (("grading", 0.02), ("grading", 0.03), ("interviewing", 0.10)):
            db.add(
                LlmCall(
                    job=job,
                    model="test-model",
                    provider="anthropic",
                    latency_ms=120,
                    input_tokens=10,
                    output_tokens=5,
                    cost_usd=cost,
                    status="settled",
                )
            )
        db.commit()

    cost_report.main()
    out = capsys.readouterr().out

    assert "calls: 3" in out
    assert "total cost: $0.1500" in out
    assert "grading: 2 call(s), $0.0500" in out
    assert "interviewing: 1 call(s), $0.1000" in out
