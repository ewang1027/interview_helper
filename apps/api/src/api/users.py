"""Who the request is for.

There is no auth (docs/API.md, "Auth"): every route is open, and this resolves the one
local user rather than authenticating anyone. It exists as a *seam* — when GitHub OAuth
lands, `current_user` is the only function that changes, and nothing downstream has to
learn that a user can be someone else.

docs/SECURITY.md's rule stands and is now due: no auth was acceptable while the surface
was `/health`, `/corpus/status` and `/execute`. Sessions write user data, so it is owed.
"""

from __future__ import annotations

from sqlmodel import Session, select

from api.models import User

# A sentinel, not a real GitHub account. `users.github_id` is unique and non-null, and
# the OAuth flow will replace this row's id with the real one on first login rather than
# creating a second user — single user, by docs/ARCHITECTURE.md.
LOCAL_GITHUB_ID = 0


def current_user(db: Session) -> User:
    """The single local user, created on first use."""
    user = db.exec(select(User).where(User.github_id == LOCAL_GITHUB_ID)).first()
    if user is None:
        user = User(github_id=LOCAL_GITHUB_ID)
        db.add(user)
        # Committed, not just flushed. A read-only route — `GET /mastery`, say — never
        # commits, so its session rolls back on close and takes the new row with it: the
        # user would be created and discarded on every such request until some write route
        # happened to persist one.
        db.commit()
        db.refresh(user)
    return user
