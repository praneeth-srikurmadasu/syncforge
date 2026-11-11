"""Mock Google Workspace Admin SDK Directory API (SIMULATED - not the real Google service).

Follows the shape of the Directory API users resource:
  POST  /oauth2/token                          issue an access token (see note below)
  GET   /admin/directory/v1/users?customer=..  connection check (list)
  POST  /admin/directory/v1/users              insert user          -> 200
  GET   /admin/directory/v1/users/{userKey}    get user (by id or primaryEmail)
  PATCH /admin/directory/v1/users/{userKey}    update user; {"suspended": true} suspends

OAuth note: the real Directory API is authorised with a service account using the
OAuth 2.0 JWT-bearer grant and domain-wide delegation. This mock simplifies that to the
OAuth 2.0 client-credentials grant (client_id + client_secret -> short-lived bearer
token), which exercises the same lifecycle in SyncForge: obtain a token, cache it, and
get a new one when it expires or is rejected.

Credentials: GOOGLE_MOCK_CLIENT_ID / GOOGLE_MOCK_CLIENT_SECRET
(defaults "syncforge-local" / "mock-google-client-secret"). Tokens live
GOOGLE_MOCK_TOKEN_TTL seconds (default 3600). POST /_mock/expire-tokens invalidates all
issued tokens at once, to simulate expiry. Errors use Google's {"error": {...}} format.

Run: uvicorn mockservices.google_workspace:app --port 9102 --app-dir mock-services
"""

import os
import secrets
import time
from typing import Any

from fastapi import Depends, FastAPI, Form, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from mockservices.faults import MockState, install

CLIENT_ID = os.environ.get("GOOGLE_MOCK_CLIENT_ID", "syncforge-local")
CLIENT_SECRET = os.environ.get("GOOGLE_MOCK_CLIENT_SECRET", "mock-google-client-secret")
TOKEN_TTL = int(os.environ.get("GOOGLE_MOCK_TOKEN_TTL", "3600"))

app = FastAPI(title="Mock Google Workspace Directory API (simulated)")
state = MockState()
tokens: dict[str, float] = {}  # access token -> expiry (epoch seconds)


def google_error(status: int, message: str) -> dict[str, Any]:
    return {"error": {"code": status, "message": message, "errors": [{"message": message}]}}


class GoogleApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message


@app.exception_handler(GoogleApiError)
async def handle_google_error(_request: Any, exc: GoogleApiError) -> JSONResponse:
    return JSONResponse(google_error(exc.status, exc.message), status_code=exc.status)


install(app, state, error_body=google_error, on_reset=tokens.clear)


@app.post("/_mock/expire-tokens", status_code=204, tags=["mock control"])
def expire_tokens() -> Response:
    tokens.clear()
    return Response(status_code=204)


@app.post("/oauth2/token")
def issue_token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...),
) -> dict[str, Any]:
    if grant_type != "client_credentials":
        raise GoogleApiError(400, "unsupported_grant_type")
    if not (
        secrets.compare_digest(client_id, CLIENT_ID)
        and secrets.compare_digest(client_secret, CLIENT_SECRET)
    ):
        raise GoogleApiError(401, "invalid_client")
    token = "ya29.mock-" + secrets.token_urlsafe(24)
    tokens[token] = time.time() + TOKEN_TTL
    return {"access_token": token, "token_type": "Bearer", "expires_in": TOKEN_TTL}


def require_token(authorization: str | None = Header(default=None)) -> None:
    token = (authorization or "").removeprefix("Bearer ")
    expiry = tokens.get(token)
    if expiry is None or expiry < time.time():
        raise GoogleApiError(401, "Invalid Credentials")


class GoogleUser(BaseModel):
    model_config = ConfigDict(extra="allow")

    primaryEmail: str  # noqa: N815 - Google attribute name
    name: dict[str, str]
    suspended: bool = False
    organizations: list[dict[str, Any]] = []
    locations: list[dict[str, Any]] = []
    externalIds: list[dict[str, Any]] = []  # noqa: N815


def _find(user_key: str) -> dict[str, Any]:
    user = state.users.get(user_key)
    if user is None:
        user = next(
            (u for u in state.users.values() if u["primaryEmail"].lower() == user_key.lower()),
            None,
        )
    if user is None:
        raise GoogleApiError(404, "Resource Not Found: userKey")
    return user


@app.get("/admin/directory/v1/users", dependencies=[Depends(require_token)])
def list_users(customer: str = "my_customer", maxResults: int = 100) -> dict[str, Any]:  # noqa: N803
    users = list(state.users.values())[:maxResults]
    return {"kind": "admin#directory#users", "users": users}


@app.post("/admin/directory/v1/users", dependencies=[Depends(require_token)])
def insert_user(body: GoogleUser) -> dict[str, Any]:
    with state.lock:
        email = body.primaryEmail.lower()
        if any(u["primaryEmail"].lower() == email for u in state.users.values()):
            raise GoogleApiError(409, "Entity already exists.")
        user_id = str(secrets.randbelow(10**20)).zfill(21)
        user = {"kind": "admin#directory#user", "id": user_id, **body.model_dump()}
        state.users[user_id] = user
        return user


@app.get("/admin/directory/v1/users/{user_key}", dependencies=[Depends(require_token)])
def get_user(user_key: str) -> dict[str, Any]:
    return _find(user_key)


@app.patch("/admin/directory/v1/users/{user_key}", dependencies=[Depends(require_token)])
def patch_user(user_key: str, body: dict[str, Any]) -> dict[str, Any]:
    with state.lock:
        user = _find(user_key)
        for key in ("id", "kind"):
            body.pop(key, None)
        user.update(body)
        return user
