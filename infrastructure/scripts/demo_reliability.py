"""Live demonstration of SyncForge's reliability engine (Phase 6).

Runs five scenarios against a locally running SyncForge (API, outbox relay, Celery worker)
and the mock Slack / Google Workspace / payroll services, injecting failures through the
mocks' control API (/_mock/faults). Everything it prints comes from the real API and the
mocks' request logs; nothing is simulated inside this script.

    1. A transient outage: payroll answers 503 twice, the step is retried and succeeds.
    2. Idempotency: a client repeats POST /employees with the same Idempotency-Key, and a
       payroll call times out after payroll had already acted - no duplicates either way.
    3. Retry exhaustion, dead-letter queue and replay.
    4. The circuit breaker: Google is down for three hires at once.
    5. A per-connector rate limit.

Prerequisites (see docs/12, section 10): PostgreSQL and Redis running, migrations applied,
and these four processes started from the repository root:

    mock services, API, Celery worker, outbox relay

Run (Windows PowerShell, from the repository root):

    & .\\backend\\.venv\\Scripts\\python.exe infrastructure\\scripts\\demo_reliability.py

With the default settings the whole run takes about two and a half minutes, most of it
the circuit breaker's 60 s open period and the dead-letter scenario's backoff (2+4+8+16 s).
Start the worker with CIRCUIT_OPEN_SECONDS=15 to make scenario 4 quicker.

It creates a new user and organization on every run and never deletes anything.
"""

import argparse
import random
import sys
import time
import uuid
from typing import Any

import httpx2 as httpx

PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - throwaway local demo account
CREDENTIALS = {
    "slack": {"token": "xoxp-mock-local-token"},
    "google_workspace": {
        "client_id": "syncforge-local",
        "client_secret": "mock-google-client-secret",
    },
    "payroll": {"api_key": "pk_mock_local_payroll_key"},
}
POSITION = {"slack": 1, "google_workspace": 2, "payroll": 3}
DONE = ("completed", "dead_letter")


def _describe(attempt: dict[str, Any]) -> str:
    text = f"#{attempt['attempt_number']} {attempt['outcome']}"
    if attempt["error_category"]:
        status = f" {attempt['http_status']}" if attempt["http_status"] else ""
        text += f" ({attempt['error_category']}{status})"
    return text


class Demo:
    def __init__(self, api: str, mocks: dict[str, str]) -> None:
        self.api = api.rstrip("/") + "/api/v1"
        self.mocks = mocks
        self.http = httpx.Client(timeout=30)
        self.t0 = time.monotonic()

    # ---- helpers -------------------------------------------------------------------

    def say(self, text: str) -> None:
        print(f"  {time.monotonic() - self.t0:6.1f} s  {text}")

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return self.http.request(method, f"{self.org_url}{path}", headers=headers, **kwargs)

    def mock(self, app: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self.http.request(method, f"{self.mocks[app]}/_mock{path}", **kwargs)

    def fault(self, app: str, **spec: Any) -> None:
        self.mock(app, "POST", "/faults", json=spec).raise_for_status()

    def clear(self, app: str) -> None:
        self.mock(app, "DELETE", "/faults")

    def mock_state(self, app: str) -> dict[str, Any]:
        return self.mock(app, "GET", "/state").json()

    def creates(self, app: str) -> int:
        """Create calls the application really received (replays excluded)."""
        return sum(
            1
            for r in self.mock_state(app)["requests"]
            if r["method"] == "POST"
            and 200 <= r["status"] < 300
            and not r.get("idempotent_replay")
            and r["path"].rstrip("/").endswith(("/Users", "/users", "/employees"))
        )

    def hire(self, **headers: str) -> str:
        n = uuid.uuid4().hex[:8]
        body = {
            "employee_number": f"E-{n}",
            "first_name": "Demo",
            "last_name": f"Hire {n}",
            "email": f"demo.{n}@acme.example",
            "joining_date": "2026-11-01",
        }
        response = self.call("POST", "/employees", json=body, headers=headers)
        response.raise_for_status()
        return response.json()["id"]

    def event(self, employee_id: str) -> dict[str, Any]:
        page = self.call("GET", "/events", params={"employee_id": employee_id}).json()
        return page["items"][0]

    def wait(self, employee_ids: list[str], *, timeout: float = 150, show: bool = True) -> None:
        last = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            states = [self.event(e)["status"] for e in employee_ids]
            if show and states != last:
                self.say("events: " + ", ".join(states))
                last = states
            if all(s in DONE for s in states):
                return
            time.sleep(0.5)
        raise SystemExit("Timed out waiting for events. Are the worker and relay running?")

    def attempts(self, employee_id: str, app: str) -> list[str]:
        event_id = self.event(employee_id)["id"]
        rows = self.call("GET", f"/events/{event_id}/attempts").json()
        return [_describe(a) for a in rows if a["position"] == POSITION[app]]

    # ---- setup ---------------------------------------------------------------------

    def setup(self) -> None:
        email = f"demo-{uuid.uuid4().hex[:8]}@example.com"
        self.http.post(
            f"{self.api}/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": "Reliability Demo"},
        ).raise_for_status()
        token = self.http.post(
            f"{self.api}/auth/login", json={"email": email, "password": PASSWORD}
        ).json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        org = self.http.post(
            f"{self.api}/organizations",
            headers=self.headers,
            json={"name": f"Reliability Demo {random.randint(1000, 9999)}"},  # noqa: S311
        ).json()
        self.org_url = f"{self.api}/organizations/{org['id']}"
        self.connectors = {}
        for app, credentials in CREDENTIALS.items():
            response = self.call(
                "POST",
                "/connectors",
                json={"connector_type": app, "name": app, "credentials": credentials},
            )
            response.raise_for_status()
            self.connectors[app] = response.json()["id"]
        steps = [{"connector_id": self.connectors[a], "operation": "create_user"} for a in POSITION]
        workflow = self.call(
            "POST",
            "/workflows",
            json={"name": "Onboarding", "trigger_event_type": "employee.created", "steps": steps},
        ).json()
        self.call("POST", f"/workflows/{workflow['id']}/activate").raise_for_status()
        for app in self.mocks:
            self.clear(app)
        print(f"Organization {org['id']}: Slack -> Google Workspace -> payroll onboarding")

    # ---- scenarios -------------------------------------------------------------------

    def transient_outage(self) -> None:
        print("\n1. Transient outage: payroll answers 503 twice")
        self.fault("payroll", kind="status", status=503, count=2, path_prefix="/v1/employees")
        employee = self.hire()
        self.wait([employee])
        self.say("payroll attempts: " + ", ".join(self.attempts(employee, "payroll")))

    def idempotency(self) -> None:
        print("\n2a. Idempotency, incoming: POST /employees twice with the same key")
        key = str(uuid.uuid4())
        n = uuid.uuid4().hex[:8]
        body = {
            "employee_number": f"E-{n}",
            "first_name": "Retry",
            "last_name": "Client",
            "email": f"retry.{n}@acme.example",
            "joining_date": "2026-11-01",
        }
        first = self.call("POST", "/employees", json=body, headers={"Idempotency-Key": key})
        second = self.call("POST", "/employees", json=body, headers={"Idempotency-Key": key})
        self.say(
            f"first {first.status_code}, second {second.status_code}; same employee: "
            f"{first.json()['id'] == second.json()['id']}; second replayed: "
            f"{second.headers.get('Idempotent-Replayed')}"
        )
        events = self.call("GET", "/events", params={"employee_id": first.json()["id"]})
        self.say(f"events recorded: {events.json()['total']} (one onboarding, not two)")
        reused = self.call(
            "POST",
            "/employees",
            json={**body, "first_name": "Other"},
            headers={"Idempotency-Key": key},
        )
        self.say(f"same key, different body: {reused.status_code} {reused.json()['error']['code']}")
        self.wait([first.json()["id"]], show=False)

        print("\n2b. Idempotency, outgoing: payroll answers only after our read timeout")
        before = self.creates("payroll")
        self.fault("payroll", kind="timeout", delay_seconds=14, path_prefix="/v1/employees")
        employee = self.hire()
        self.wait([employee])
        self.say("payroll attempts: " + ", ".join(self.attempts(employee, "payroll")))
        self.say(f"payroll records actually created: {self.creates('payroll') - before}")

    def dead_letter_and_replay(self) -> None:
        print("\n3. Retries exhausted -> dead-letter queue -> replay")
        self.fault("payroll", kind="status", status=503, count=1000, path_prefix="/v1/employees")
        employee = self.hire()
        self.wait([employee])
        queue = self.call("GET", "/dead-letter-events", params={"entry_status": "open"}).json()
        entry = queue["items"][0]
        self.say(
            f"dead-letter entry: {entry['reason']}, {entry['operation']} "
            f"{entry['error_category']} {entry['http_status']}, {entry['attempts']} attempts"
        )
        self.clear("payroll")
        test = self.call("POST", f"/connectors/{self.connectors['payroll']}/test").json()
        self.say(f"payroll recovered; connection test ok={test['ok']} (also closes its circuit)")
        replay = self.call("POST", f"/dead-letter-events/{entry['id']}/replay")
        again = self.call("POST", f"/dead-letter-events/{entry['id']}/replay")
        self.say(
            f"replay: {replay.status_code}; replay again: {again.status_code} "
            f"{again.json()['error']['code']}"
        )
        self.wait([employee])
        self.say("payroll attempts: " + ", ".join(self.attempts(employee, "payroll")))

    def circuit_breaker(self) -> None:
        print("\n4. Circuit breaker: Google is down while three people are hired")
        before = self.creates("google_workspace")
        calls_before = len(self.mock_state("google_workspace")["requests"])
        self.fault(
            "google_workspace",
            kind="status",
            status=503,
            count=1000,
            path_prefix="/admin/directory",
        )
        employees = [self.hire() for _ in range(3)]
        recovered = False
        last = None
        deadline = time.monotonic() + 200
        while time.monotonic() < deadline:
            circuit = self.call("GET", f"/connectors/{self.connectors['google_workspace']}")
            state = circuit.json()["circuit"]["state"]
            calls = len(self.mock_state("google_workspace")["requests"]) - calls_before
            states = [self.event(e)["status"] for e in employees]
            if (state, calls, states) != last:
                self.say(
                    f"circuit {state:<9} Google requests {calls:>2}  events {', '.join(states)}"
                )
                last = (state, calls, states)
            if state == "open" and not recovered:
                time.sleep(3)
                self.clear("google_workspace")
                recovered = True
                self.say(
                    "-- Google is back; the breaker lets one trial call through when "
                    "its open period ends --"
                )
            if all(s in DONE for s in states):
                break
            time.sleep(0.5)
        for i, employee in enumerate(employees, 1):
            self.say(
                f"hire {i} Google attempts: "
                + ", ".join(self.attempts(employee, "google_workspace"))
            )
        self.say(f"Google accounts created: {self.creates('google_workspace') - before}")

    def rate_limit(self) -> None:
        print("\n5. Rate limit: Slack limited to 2 calls per minute, three hires")
        self.call(
            "PATCH",
            f"/connectors/{self.connectors['slack']}",
            json={"config": {"rate_limit_per_minute": 2}},
        ).raise_for_status()
        employees = [self.hire() for _ in range(3)]
        self.wait(employees)
        for i, employee in enumerate(employees, 1):
            self.say(f"hire {i} Slack attempts: " + ", ".join(self.attempts(employee, "slack")))
        self.say("the third hire waited for the next minute without using an attempt")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--slack", default="http://127.0.0.1:9101")
    parser.add_argument("--google", default="http://127.0.0.1:9102")
    parser.add_argument("--payroll", default="http://127.0.0.1:9103")
    args = parser.parse_args()
    demo = Demo(
        args.api,
        {"slack": args.slack, "google_workspace": args.google, "payroll": args.payroll},
    )
    try:
        demo.http.get(f"{args.api}/ready").raise_for_status()
        for app in demo.mocks:
            demo.mock_state(app)
    except httpx.HTTPError as exc:
        print(f"Cannot reach the API or a mock service: {exc}", file=sys.stderr)
        return 1
    demo.setup()
    demo.transient_outage()
    demo.idempotency()
    demo.dead_letter_and_replay()
    demo.circuit_breaker()
    demo.rate_limit()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
