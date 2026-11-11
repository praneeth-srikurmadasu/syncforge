"""Mock payroll API (SIMULATED - a generic REST payroll system, not a real product).

  GET   /v1/ping                    connection check
  POST  /v1/employees               create payroll record      -> 201
  GET   /v1/employees/{id}          read record
  PATCH /v1/employees/{id}          update; {"status": "inactive"} ends payroll

Auth: `X-API-Key: <key>`; the key is PAYROLL_MOCK_API_KEY
(default "pk_mock_local_payroll_key"). employee_number is unique.

Run: uvicorn mockservices.payroll:app --port 9103 --app-dir mock-services
"""

import os
import secrets
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from mockservices.faults import MockState, install

API_KEY = os.environ.get("PAYROLL_MOCK_API_KEY", "pk_mock_local_payroll_key")

app = FastAPI(title="Mock Payroll API (simulated)")
state = MockState()


def payroll_error(status: int, message: str) -> dict[str, Any]:
    return {"error": {"status": status, "message": message}}


class PayrollApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message


@app.exception_handler(PayrollApiError)
async def handle_payroll_error(_request: Any, exc: PayrollApiError) -> JSONResponse:
    return JSONResponse(payroll_error(exc.status, exc.message), status_code=exc.status)


install(app, state, error_body=payroll_error)


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key is None or not secrets.compare_digest(x_api_key, API_KEY):
        raise PayrollApiError(401, "Invalid API key.")


class PayrollRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_number: str
    first_name: str
    last_name: str
    email: str
    department: str | None = None
    designation: str | None = None
    location: str | None = None
    status: Literal["active", "inactive"] = "active"


class PayrollUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    department: str | None = None
    designation: str | None = None
    location: str | None = None
    status: Literal["active", "inactive"] | None = None


def _get(record_id: str) -> dict[str, Any]:
    record = state.users.get(record_id)
    if record is None:
        raise PayrollApiError(404, "Payroll record not found.")
    return record


@app.get("/v1/ping", dependencies=[Depends(require_key)])
def ping() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/employees", status_code=201, dependencies=[Depends(require_key)])
def create_record(body: PayrollRecord) -> dict[str, Any]:
    with state.lock:
        if any(r["employee_number"] == body.employee_number for r in state.users.values()):
            raise PayrollApiError(409, "A payroll record already exists for this employee.")
        record_id = "PR-" + secrets.token_hex(4).upper()
        record = {"id": record_id, **body.model_dump()}
        state.users[record_id] = record
        return record


@app.get("/v1/employees/{record_id}", dependencies=[Depends(require_key)])
def get_record(record_id: str) -> dict[str, Any]:
    return _get(record_id)


@app.patch("/v1/employees/{record_id}", dependencies=[Depends(require_key)])
def update_record(record_id: str, body: PayrollUpdate) -> dict[str, Any]:
    with state.lock:
        record = _get(record_id)
        record.update(body.model_dump(exclude_unset=True))
        return record
