"""Who this deployment serves.

Single user, by docs/ARCHITECTURE.md, on a schema that is multi-tenant-shaped so it never
needs a rewrite. Two resolvers live here and they answer different questions:

- `user_for_github_id` — the OAuth callback's. The row for the account that has just
  proved who it is, **adopting** the pre-auth sentinel row rather than orphaning the
  evidence written before there was any login.
- `single_user` — the operator's. The row `python -m api.mint_session` signs a cookie
  for, and the one the tests use. It resolves the existing user rather than the sentinel
  specifically, so minting a cookie after a real login does not invent a second account.

Nothing here authenticates anyone: `api.auth` does that, and hands routes a `Principal`.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, col, select

from api.models import User

logger = logging.getLogger(__name__)

# A sentinel, not a real GitHub account. `users.github_id` is unique and non-null, so the
# row that exists before anyone has logged in needs *some* value; the first successful
# login rewrites this one in place rather than creating a second user.
LOCAL_GITHUB_ID = 0


def single_user(db: Session) -> User:
    """The one user this deployment serves, created on first use."""
    user = db.exec(select(User).order_by(col(User.created_at))).first()
    if user is None:
        user = User(github_id=LOCAL_GITHUB_ID)
        db.add(user)
        # Committed, not just flushed. A caller that never commits — a read-only route, a
        # test that only reads — rolls back on close and takes the new row with it: the
        # user would be created and discarded until some write happened to persist one.
        db.commit()
        db.refresh(user)
    return user


def user_for_github_id(db: Session, github_id: int) -> User:
    """The row for an authenticated GitHub account, adopting the sentinel if it is free.

    Adoption is what keeps the first login from stranding history: every
    `concept_evidence` row written before auth existed is keyed to the sentinel's user id,
    and creating a second row for the same person would leave that evidence behind a user
    nobody can log in as.
    """
    user = db.exec(select(User).where(User.github_id == github_id)).first()
    if user is not None:
        return user

    sentinel = db.exec(select(User).where(User.github_id == LOCAL_GITHUB_ID)).first()
    if sentinel is not None:
        sentinel.github_id = github_id
        db.add(sentinel)
        db.commit()
        db.refresh(sentinel)
        logger.info("adopted the pre-auth user row for github id %s", github_id)
        return sentinel

    # No sentinel left, so a different account has logged in here before. Allowed by the
    # schema and visible immediately — the new user's mastery is empty — but it means the
    # configured account changed, which is worth a line in the log rather than silence.
    logger.warning("creating a second user for github id %s", github_id)
    user = User(github_id=github_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
