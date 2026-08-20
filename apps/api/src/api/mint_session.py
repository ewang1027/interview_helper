"""Sign a session cookie for the local user, from the command line.

`api.auth` deliberately has no local-login route: a route that issues a session without
GitHub is a route that exists in production too, whatever flag is supposed to be guarding
it. Development still needs a cookie, so it is minted *outside* the process, by whoever
already holds `SESSION_SECRET` — which is the same thing the server verifies with, so this
grants nothing that possessing the secret did not already grant.

    make login                                  # a cookie and a curl line
    TOKEN=$(uv run python -m api.mint_session --raw)

Needs the database as well as the secret: a session cookie names a real `users` row, and
inventing an id would produce a cookie that authenticates as nobody.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from api.auth import SESSION_COOKIE, SESSION_TTL_SECONDS, session_token
from api.db import get_engine
from api.settings import get_settings
from api.users import LOCAL_GITHUB_ID, single_user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--raw", action="store_true", help="print only the token, for capturing in a variable"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.session_secret:
        print(
            "SESSION_SECRET is not set. Generate one and put it in .env:\n"
            "  python -c 'import secrets; print(secrets.token_urlsafe(48))'",
            file=sys.stderr,
        )
        return 1

    with Session(get_engine()) as db:
        user = single_user(db)
        token = session_token(
            user_id=user.id, github_id=user.github_id, secret=settings.session_secret
        )
        github_id = user.github_id

    if args.raw:
        print(token)
        return 0

    expires = (datetime.now(UTC) + timedelta(seconds=SESSION_TTL_SECONDS)).strftime("%Y-%m-%d")
    account = "the pre-auth local row" if github_id == LOCAL_GITHUB_ID else f"github id {github_id}"
    print(f"# session for {account}, valid until {expires}")
    print(f"export IH_COOKIE='{SESSION_COOKIE}={token}'")
    print('curl -s -H "Cookie: $IH_COOKIE" http://localhost:8000/api/v1/mastery')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
