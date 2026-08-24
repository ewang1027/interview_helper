"""Authentication: GitHub OAuth in, a signed cookie afterwards.

docs/API.md specifies it in one paragraph — single user, GitHub OAuth, a signed session
cookie, one allowed account id in config, everything under `/api/v1` behind it except
`/health`. This is that, and the choices it left open, made:

**The cookie is signed, not encrypted, and holds no secret** — a user id, the GitHub id it
belongs to, and an expiry. HMAC-SHA256 over a compact JSON body, stdlib only. A session
store in Postgres would allow instant revocation; for one user whose only revocation event
is rotating `SESSION_SECRET`, it would be a table to keep consistent for nothing.

**Nothing else mints a session.** There is no local-login route, no dev bypass and no
`AUTH_MODE`, because a mode flag is a thing that can be wrong in production. Development
uses `python -m api.mint_session`, which signs a cookie from the same secret *outside* the
process — so the deployed API has no code path at all that issues a session without
GitHub, rather than one that is merely switched off.

**Verification never touches the database.** A `Principal` is what the signature already
proved, so `GET /api/v1/corpus/status` stays a route that needs no connection. The cost is
that a deleted user's cookie keeps working until it expires; with one user, that state
does not arise.

Not here, deliberately: rate limiting (docs/SECURITY.md), token refresh (a 30-day cookie
and one user), and the Vapi shared-secret header, which is Phase 7's (docs/VOICE.md).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlmodel import Session

from api.db import get_session
from api.errors import ProblemError, forbidden, not_configured, unauthenticated, unavailable
from api.settings import Settings, get_settings
from api.users import user_for_github_id

logger = logging.getLogger(__name__)

SESSION_COOKIE = "ih_session"
STATE_COOKIE = "ih_oauth_state"

# Thirty days. Long, because the alternative for a single user on their own machine is
# re-authenticating with GitHub every week for no threat that is being defended against.
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
# The round trip to GitHub and back. Ten minutes is generous for a redirect and short
# enough that a state cookie left behind on an abandoned login is not a standing key.
STATE_TTL_SECONDS = 10 * 60

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105 - a URL
GITHUB_USER_URL = "https://api.github.com/user"

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Signing ------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(body: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def sign(payload: dict[str, Any], secret: str) -> str:
    """`<base64url(json)>.<base64url(hmac-sha256)>`."""
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{body}.{_mac(body, secret)}"


def verify(token: str, secret: str, *, now: float | None = None) -> dict[str, Any] | None:
    """The payload, or None for anything that is not a live signature of ours.

    The order matters: the MAC is checked *before* the body is decoded, so unauthenticated
    input is never parsed. A caller cannot tell a forged signature from an expired one,
    which is deliberate — both mean "log in again".
    """
    body, separator, mac = token.partition(".")
    if not body or not separator or not mac:
        return None
    if not hmac.compare_digest(mac, _mac(body, secret)):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expires = payload.get("exp")
    if not isinstance(expires, int | float) or expires <= (now if now is not None else time.time()):
        return None
    return payload


def session_token(*, user_id: str, github_id: int, secret: str, issued: float | None = None) -> str:
    now = time.time() if issued is None else issued
    return sign(
        {"uid": user_id, "gid": github_id, "iat": int(now), "exp": int(now) + SESSION_TTL_SECONDS},
        secret,
    )


# --- What a verified request is ------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, as proved by the signature and nothing else."""

    user_id: str
    github_id: int


def _secret(settings: Settings) -> str:
    if not settings.session_secret:
        # 503, not 401: the request is fine and no credential would help. Saying so names
        # the one thing an operator has to fix, which a bare 401 would send them past.
        raise not_configured("SESSION_SECRET is not set, so no session can be verified.")
    return settings.session_secret


def require_principal(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Principal:
    """The dependency `/api/v1` is mounted behind. `/health` is outside the prefix."""
    # The secret is resolved before the cookie is looked at, not after. Reading the cookie
    # first meant a server with no `SESSION_SECRET` answered "sign in at /auth/login" to a
    # request carrying no cookie — advice that cannot be followed, since the login flow
    # needs the same missing secret. A test caught it; the ordering here is the fix.
    secret = _secret(settings)
    token = request.cookies.get(SESSION_COOKIE)
    payload = verify(token, secret) if token else None
    if payload is None:
        raise unauthenticated("Sign in at /auth/login.")
    user_id, github_id = payload.get("uid"), payload.get("gid")
    if not isinstance(user_id, str) or not isinstance(github_id, int):
        # Signed by us and still not a session: a state that only a bug can produce, so it
        # fails closed rather than guessing what the payload meant.
        logger.warning("session cookie carried an unexpected payload: %s", sorted(payload))
        raise unauthenticated("Sign in at /auth/login.")
    return Principal(user_id=user_id, github_id=github_id)


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]


# --- GitHub --------------------------------------------------------------------------


class GitHubOAuth:
    """The two calls the login flow makes, behind one object so a test can substitute the
    whole conversation instead of patching httpx."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=10.0)

    def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.post(url, **kwargs)
        except httpx.HTTPError as exc:
            raise unavailable(f"GitHub did not answer: {exc}") from exc

    def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.get(url, **kwargs)
        except httpx.HTTPError as exc:
            raise unavailable(f"GitHub did not answer: {exc}") from exc

    def exchange_code(
        self, *, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> str:
        response = self._post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        # GitHub answers a rejected code with 200 and an `error` field, so status alone
        # says nothing.
        body = _json_body(response)
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise ProblemError(
                status=400,
                slug="oauth-failed",
                title="GitHub rejected the login",
                detail=str(body.get("error_description") or body.get("error") or "No token."),
            )
        return token

    def account_id(self, access_token: str) -> int:
        response = self._get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if response.status_code != 200:
            raise unavailable(f"GitHub returned {response.status_code} for the account lookup.")
        account = _json_body(response).get("id")
        if not isinstance(account, int):
            raise unavailable("GitHub's account response carried no numeric id.")
        return account


def _json_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise unavailable("GitHub's response was not JSON.") from exc
    return body if isinstance(body, dict) else {}


@lru_cache
def _github() -> GitHubOAuth:
    return GitHubOAuth()


def get_github() -> GitHubOAuth:
    """Injected, so a test overrides the dependency rather than the network."""
    return _github()


# --- Routes ---------------------------------------------------------------------------

DbSession = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
GitHub = Annotated[GitHubOAuth, Depends(get_github)]


def _oauth_config(settings: Settings) -> tuple[str, str, int]:
    """The three OAuth values, or a refusal naming the ones that are unset.

    `GITHUB_ALLOWED_ID` is checked for falsiness rather than None: 0 is the pre-auth
    sentinel in `api.users`, no GitHub account has it, and an allowed id of zero would
    mean nobody can log in — which is a misconfiguration worth naming, not honouring.
    """
    client_id = settings.github_client_id
    client_secret = settings.github_client_secret
    allowed_id = settings.github_allowed_id
    if not client_id or not client_secret or not allowed_id or not settings.session_secret:
        # An OAuth app with no allowed account would authenticate *any* GitHub user
        # against a single-user deployment, so an incomplete configuration refuses the
        # flow rather than running a weaker version of it.
        missing = [
            name
            for name, value in (
                ("GITHUB_CLIENT_ID", client_id),
                ("GITHUB_CLIENT_SECRET", client_secret),
                ("GITHUB_ALLOWED_ID", allowed_id),
                ("SESSION_SECRET", settings.session_secret),
            )
            if not value
        ]
        raise not_configured(f"OAuth is not configured: {', '.join(missing)} unset.")
    return client_id, client_secret, allowed_id


def _set_cookie(response: Response, name: str, value: str, *, ttl: int, secure: bool) -> None:
    response.set_cookie(
        name,
        value,
        max_age=ttl,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


@router.get("/login")
def login(settings: Config) -> Response:
    """Redirect to GitHub, carrying a signed one-shot `state`.

    The state is signed *and* echoed in a cookie: the signature proves we issued it, and
    the cookie comparison proves this browser is the one that started the flow. Either
    alone leaves login-CSRF open — an attacker who can obtain a valid state from their own
    login can otherwise complete it in your browser and land you in their account.
    """
    client_id, _, _ = _oauth_config(settings)
    secret = _secret(settings)
    nonce = secrets.token_urlsafe(24)
    state = sign({"n": nonce, "exp": int(time.time()) + STATE_TTL_SECONDS}, secret)
    query = httpx.QueryParams(
        {
            "client_id": client_id,
            "redirect_uri": settings.github_redirect_uri,
            "scope": "read:user",
            "state": state,
            "allow_signup": "false",
        }
    )
    response = RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{query}", status_code=302)
    _set_cookie(response, STATE_COOKIE, state, ttl=STATE_TTL_SECONDS, secure=settings.cookie_secure)
    return response


@router.get("/callback")
def callback(
    request: Request,
    settings: Config,
    github: GitHub,
    db: DbSession,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> Response:
    """Exchange the code, check the account, adopt the user row, set the cookie.

    This used to answer JSON unconditionally, "because there is no web app to redirect to
    until Phase 5". Phase 5 landed on 2026-08-24 and the premise expired with it — a
    browser completing a login was left looking at a JSON document, having to find its own
    way back to an app that now exists.

    So a browser is sent home and everything else still gets the body. The two are told
    apart by `Accept`, because that is the one thing a browser navigation reliably says
    about itself: GitHub sends a *browser* here, while the tests and any tooling that
    drives the flow want `user_id` and `github_id` rather than a 303.

    The redirect is **relative**, deliberately. It resolves against whichever origin
    served the request, which is necessarily the origin the cookie was just set on — so
    running the flow through the web app's proxy sends the user back to the web app, and
    no second setting can disagree with `GITHUB_REDIRECT_URI` about where "home" is.
    """
    client_id, client_secret, allowed_id = _oauth_config(settings)
    secret = _secret(settings)

    issued = request.cookies.get(STATE_COOKIE)
    if not issued or not secrets.compare_digest(issued, state) or verify(state, secret) is None:
        raise ProblemError(
            status=400,
            slug="oauth-state-mismatch",
            title="The login could not be verified",
            detail="The state parameter did not match this browser's, or it expired.",
        )

    token = github.exchange_code(
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=settings.github_redirect_uri,
    )
    account = github.account_id(token)
    if account != allowed_id:
        logger.warning("refused a login from github id %s", account)
        raise forbidden("That GitHub account is not the one this deployment serves.")

    user = user_for_github_id(db, account)
    wants_html = "text/html" in request.headers.get("accept", "")
    response: Response = (
        RedirectResponse("/", status_code=303)
        if wants_html
        else JSONResponse({"authenticated": True, "user_id": user.id, "github_id": account})
    )
    _set_cookie(
        response,
        SESSION_COOKIE,
        session_token(user_id=user.id, github_id=account, secret=secret),
        ttl=SESSION_TTL_SECONDS,
        secure=settings.cookie_secure,
    )
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@router.get("/me")
def me(principal: CurrentPrincipal) -> dict[str, Any]:
    """200 with who you are, 401 with a problem document if the cookie is not valid."""
    return {"authenticated": True, "user_id": principal.user_id, "github_id": principal.github_id}


@router.post("/logout", status_code=204)
def logout() -> Response:
    """Clears the cookie. The token stays valid until it expires — there is no server-side
    session to revoke, which is the trade `SESSION_SECRET` rotation exists to settle."""
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
