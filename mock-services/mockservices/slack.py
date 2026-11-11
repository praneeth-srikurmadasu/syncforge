"""Mock Slack SCIM API (SIMULATED - not the real Slack service).

Follows the shape of Slack's SCIM v2 user provisioning API:
  GET    /scim/v2/ServiceProviderConfig   connection check
  POST   /scim/v2/Users                   create user            -> 201
  GET    /scim/v2/Users/{id}              read user
  PATCH  /scim/v2/Users/{id}              SCIM PatchOp (replace)
  DELETE /scim/v2/Users/{id}              deactivate (Slack keeps the user, active=false)

Auth: `Authorization: Bearer <token>`; the token is SLACK_MOCK_TOKEN
(default "xoxp-mock-local-token"). Errors use the SCIM error format.

Run: uvicorn mockservices.slack:app --port 9101 --app-dir mock-services
"""

import os
import secrets
from typing import Any

from fastapi import Depends, FastAPI, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from mockservices.faults import MockState, install

SCIM_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
SCIM_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
TOKEN = os.environ.get("SLACK_MOCK_TOKEN", "xoxp-mock-local-token")

app = FastAPI(title="Mock Slack SCIM API (simulated)")
state = MockState()


def scim_error(status: int, detail: str) -> dict[str, Any]:
    return {"schemas": [SCIM_ERROR], "status": str(status), "detail": detail}


class ScimError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


@app.exception_handler(ScimError)
async def handle_scim_error(_request: Any, exc: ScimError) -> JSONResponse:
    return JSONResponse(scim_error(exc.status, exc.detail), status_code=exc.status)


install(app, state, error_body=scim_error)


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not secrets.compare_digest(authorization or "", f"Bearer {TOKEN}"):
        raise ScimError(401, "invalid_authentication")


class ScimUser(BaseModel):
    model_config = ConfigDict(extra="allow")

    userName: str  # noqa: N815 - SCIM attribute name
    name: dict[str, str] = {}
    emails: list[dict[str, Any]] = []
    active: bool = True
    title: str | None = None


class PatchOp(BaseModel):
    model_config = ConfigDict(extra="allow")

    Operations: list[dict[str, Any]]  # noqa: N815 - SCIM attribute name


def _get(user_id: str) -> dict[str, Any]:
    user = state.users.get(user_id)
    if user is None:
        raise ScimError(404, "user_not_found")
    return user


@app.get("/scim/v2/ServiceProviderConfig", dependencies=[Depends(require_token)])
def service_provider_config() -> dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "filter": {"supported": True, "maxResults": 100},
    }


@app.post("/scim/v2/Users", status_code=201, dependencies=[Depends(require_token)])
def create_user(body: ScimUser) -> dict[str, Any]:
    with state.lock:
        emails = {e.get("value", "").lower() for e in body.emails}
        for existing in state.users.values():
            existing_emails = {e.get("value", "").lower() for e in existing["emails"]}
            if existing["userName"] == body.userName or emails & existing_emails:
                raise ScimError(409, "user_already_exists")
        user_id = "U" + secrets.token_hex(5).upper()
        user = {"schemas": [SCIM_USER], "id": user_id, **body.model_dump()}
        state.users[user_id] = user
        return user


@app.get("/scim/v2/Users/{user_id}", dependencies=[Depends(require_token)])
def get_user(user_id: str) -> dict[str, Any]:
    return _get(user_id)


@app.patch("/scim/v2/Users/{user_id}", dependencies=[Depends(require_token)])
def patch_user(user_id: str, body: PatchOp) -> dict[str, Any]:
    with state.lock:
        user = _get(user_id)
        for operation in body.Operations:
            if operation.get("op", "").lower() != "replace" or not isinstance(
                operation.get("value"), dict
            ):
                raise ScimError(400, "invalid_patch_operation")
            user.update(operation["value"])
        return user


@app.delete("/scim/v2/Users/{user_id}", dependencies=[Depends(require_token)])
def deactivate_user(user_id: str) -> Response:
    with state.lock:
        _get(user_id)["active"] = False
    return Response(status_code=204)
