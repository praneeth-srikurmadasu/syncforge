"""Performance measurements for SyncForge.

Measures, against a locally running stack, and prints a report plus a JSON file:

1. API latency - sequential requests to common endpoints (warm-up first), with
   p50 / p95 / p99 / mean per endpoint, measured by this client (includes HTTP and
   loopback networking, not browser rendering).
2. Event throughput - N hires sent back to back to an organization with an active
   three-step onboarding workflow (Slack -> Google Workspace -> payroll, the local mocks);
   time from the first hire until every event completed, and per-event durations from
   the events' own timestamps.
3. Database query plans - EXPLAIN (ANALYZE, BUFFERS) of the queries behind the busiest
   endpoints, on the seeded organization, with execution times and whether an index is
   used.

Every number comes from this run on this machine. The report records the environment
(CPU, memory, OS, Python, PostgreSQL) so results can be compared honestly, and they are
not production figures: everything runs on one machine, with one worker process.

Prerequisites: PostgreSQL and Redis running, migrations applied, and the mock services,
API, Celery worker and outbox relay started (CONTRIBUTING.md, Development setup). Run from the
repository root with the backend's interpreter (it reads DATABASE_URL like the API):

    & .\\backend\\.venv\\Scripts\\python.exe infrastructure\\scripts\\benchmark.py

Options: --employees (organization size, default 1000), --requests (per endpoint,
default 200), --hires (default 100), --workers (how many worker processes you started,
recorded in the report; default 1), --output (JSON file). It creates a new user and
organization on every run and never deletes anything.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2 as httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

PASSWORD = "tulip-river-48-bench"  # noqa: S105 - throwaway local account
CREDENTIALS = {
    "slack": {"token": "xoxp-mock-local-token"},
    "google_workspace": {
        "client_id": "syncforge-local",
        "client_secret": "mock-google-client-secret",
    },
    "payroll": {"api_key": "pk_mock_local_payroll_key"},
}
LAST_NAMES = [
    "Adams", "Baker", "Clark", "Davis", "Evans", "Fisher", "Garcia", "Hughes", "Iyer", "Jones",
    "Khan", "Lopez", "Mehta", "Nair", "Ortiz", "Patel", "Quinn", "Rao", "Shah", "Turner",
]  # fmt: skip
DEPARTMENTS = ["Engineering", "Finance", "Sales", "Product", "People Operations"]


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100)."""
    ordered = sorted(values)
    rank = max(1, round(q / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def summarize(ms: list[float]) -> dict[str, float]:
    return {
        "n": len(ms),
        "p50_ms": round(percentile(ms, 50), 2),
        "p95_ms": round(percentile(ms, 95), 2),
        "p99_ms": round(percentile(ms, 99), 2),
        "mean_ms": round(statistics.fmean(ms), 2),
    }


def environment(db_version: str) -> dict[str, Any]:
    cpu = platform.processor() or platform.machine()
    memory_gb: float | None = None
    try:  # Linux
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            cpu = next(line.split(":", 1)[1].strip() for line in f if line.startswith("model name"))
        with open("/proc/meminfo", encoding="utf-8") as f:
            kb = int(next(line.split()[1] for line in f if line.startswith("MemTotal")))
            memory_gb = round(kb / 1024 / 1024, 1)
    except (OSError, StopIteration):
        pass
    return {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "os": platform.platform(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "memory_gb": memory_gb,
        "python": platform.python_version(),
        "postgresql": db_version,
    }


class Bench:
    def __init__(self, api: str) -> None:
        self.base = api.rstrip("/")
        self.http = httpx.Client(timeout=60)

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.org_url}{path}"
        return self.http.request(method, url, headers=self.headers, **kwargs)

    # ---- setup ------------------------------------------------------------------------

    def setup(self, employees: int) -> None:
        email = f"bench-{uuid.uuid4().hex[:8]}@example.com"
        api = f"{self.base}/api/v1"
        self.http.post(
            f"{api}/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": "Benchmark"},
        ).raise_for_status()
        token = self.http.post(
            f"{api}/auth/login", json={"email": email, "password": PASSWORD}
        ).json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        org = self.http.post(
            f"{api}/organizations",
            headers=self.headers,
            json={"name": f"Benchmark {uuid.uuid4().hex[:6]}"},
        )
        org.raise_for_status()
        self.org_id = org.json()["id"]
        self.org_url = f"{api}/organizations/{self.org_id}"
        self.v2_url = f"{self.base}/api/v2/organizations/{self.org_id}"
        departments = [
            self.call("POST", "/departments", json={"name": name}).json()["id"]
            for name in DEPARTMENTS
        ]
        started = time.perf_counter()
        for i in range(employees):
            self.hire(i, departments[i % len(departments)])
        seconds = time.perf_counter() - started
        print(f"Seeded {employees} employees in {seconds:.1f} s (no workflows active yet)")
        self.wait_until_idle()

    def hire(self, i: int, department_id: str | None = None) -> str:
        n = uuid.uuid4().hex[:8]
        body = {
            "employee_number": f"B-{n}",
            "first_name": f"Person{i}",
            "last_name": LAST_NAMES[i % len(LAST_NAMES)],
            "email": f"bench.{n}@acme.example",
            "joining_date": "2026-11-01",
        }
        if department_id:
            body["department_id"] = department_id
        response = self.call("POST", "/employees", json=body)
        response.raise_for_status()
        return response.json()["id"]

    def wait_until_idle(self, timeout: float = 900) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = self.call("GET", "/summary").json()["events"]
            if events["pending"] + events["processing"] + events["retrying"] == 0:
                return
            time.sleep(0.5)
        raise SystemExit("Timed out waiting for events. Are the worker and relay running?")

    # ---- 1. API latency ---------------------------------------------------------------

    def latency(self, requests: int) -> dict[str, dict[str, float]]:
        some_employee = self.call("GET", "/employees", params={"limit": 1}).json()["items"][0]
        deep_cursor = self.v2_cursor_at(depth=max(0, self.employee_count - 20))
        endpoints: dict[str, tuple[str, str, dict[str, Any]]] = {
            "GET v1 employees (page 1, 20 rows)": (
                "GET",
                "/employees",
                {"params": {"limit": 20}},
            ),
            "GET v1 employees (last page, offset)": (
                "GET",
                "/employees",
                {"params": {"limit": 20, "offset": max(0, self.employee_count - 20)}},
            ),
            "GET v2 employees (page 1, 20 rows)": (
                "GET",
                f"{self.v2_url}/employees",
                {"params": {"limit": 20}},
            ),
            "GET v2 employees (last page, cursor)": (
                "GET",
                f"{self.v2_url}/employees",
                {"params": {"limit": 20, "cursor": deep_cursor}},
            ),
            "GET v1 employees search": (
                "GET",
                "/employees",
                {"params": {"search": "person4"}},
            ),
            "GET employee detail": ("GET", f"/employees/{some_employee['id']}", {}),
            "GET organization summary": ("GET", "/summary", {}),
            "GET events (page 1)": ("GET", "/events", {"params": {"limit": 20}}),
        }
        results: dict[str, dict[str, float]] = {}
        for name, (method, path, kwargs) in endpoints.items():
            for _ in range(min(20, requests)):  # warm-up: connection, caches, plans
                self.call(method, path, **kwargs).raise_for_status()
            timings = []
            for _ in range(requests):
                start = time.perf_counter()
                response = self.call(method, path, **kwargs)
                timings.append((time.perf_counter() - start) * 1000)
                response.raise_for_status()
            results[name] = summarize(timings)
            _print_latency(name, results[name])

        # Writes: each request creates an employee (and an event, no active workflow).
        timings = []
        for i in range(requests):
            start = time.perf_counter()
            self.hire(100_000 + i)
            timings.append((time.perf_counter() - start) * 1000)
        results["POST employee (create)"] = summarize(timings)
        _print_latency("POST employee (create)", results["POST employee (create)"])
        self.wait_until_idle()
        return results

    def v2_cursor_at(self, depth: int) -> str | None:
        cursor, seen = None, 0
        while seen < depth:
            params: dict[str, Any] = {"limit": min(100, depth - seen)}
            if cursor:
                params["cursor"] = cursor
            page = self.call("GET", f"{self.v2_url}/employees", params=params).json()
            seen += len(page["data"])
            cursor = page["page"]["next_cursor"]
            if cursor is None:
                break
        return cursor

    # ---- 2. Event throughput ----------------------------------------------------------

    def throughput(self, hires: int) -> dict[str, Any]:
        connectors = {}
        for app, credentials in CREDENTIALS.items():
            response = self.call(
                "POST",
                "/connectors",
                json={"connector_type": app, "name": app, "credentials": credentials},
            )
            response.raise_for_status()
            connectors[app] = response.json()["id"]
        steps = [
            {"connector_id": connectors[a], "operation": "create_user"}
            for a in ("slack", "google_workspace", "payroll")
        ]
        workflow = self.call(
            "POST",
            "/workflows",
            json={
                "name": "Onboarding",
                "trigger_event_type": "employee.created",
                "steps": steps,
            },
        ).json()
        self.call("POST", f"/workflows/{workflow['id']}/activate").raise_for_status()

        started = time.perf_counter()
        started_at = datetime.now(UTC)
        ids = [self.hire(200_000 + i) for i in range(hires)]
        submitted = time.perf_counter() - started
        self.wait_until_idle()
        finished = time.perf_counter() - started

        events = []
        for employee_id in ids:
            page = self.call(
                "GET",
                "/events",
                params={"employee_id": employee_id, "event_type": "employee.created"},
            ).json()
            events.append(page["items"][0])
        statuses = {e["status"] for e in events}
        end_to_end = [
            (_ts(e["completed_at"]) - _ts(e["created_at"])).total_seconds() * 1000 for e in events
        ]
        attempt = [
            (_ts(e["completed_at"]) - _ts(e["started_at"])).total_seconds() * 1000 for e in events
        ]
        last_done = max(_ts(e["completed_at"]) for e in events)
        result = {
            "hires": hires,
            "steps_per_event": 3,
            "submitted_in_s": round(submitted, 2),
            "all_completed_in_s": round(finished, 2),
            "events_per_second": round(hires / (last_done - started_at).total_seconds(), 2),
            "external_calls_per_second": round(
                hires * 3 / (last_done - started_at).total_seconds(), 2
            ),
            "statuses": sorted(statuses),
            "end_to_end": summarize(end_to_end),
            "final_attempt": summarize(attempt),
        }
        print(
            f"  {hires} hires submitted in {submitted:.1f} s; all completed after "
            f"{finished:.1f} s; {result['events_per_second']} events/s "
            f"({result['external_calls_per_second']} external calls/s); statuses {sorted(statuses)}"
        )
        print(
            f"  per event: end to end p50 {result['end_to_end']['p50_ms']} ms, p95 "
            f"{result['end_to_end']['p95_ms']} ms; worker time p50 "
            f"{result['final_attempt']['p50_ms']} ms, p95 {result['final_attempt']['p95_ms']} ms"
        )
        return result

    # ---- 3. Query plans ---------------------------------------------------------------

    def plans(self) -> tuple[str, dict[str, Any]]:
        from sqlalchemy import text

        from app.core.database import engine

        org = self.org_id
        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar_one()
            boundary = conn.execute(
                text(
                    "SELECT last_name, first_name, id FROM employees "
                    "WHERE organization_id = :o AND archived_at IS NULL "
                    "ORDER BY last_name, first_name, id OFFSET :n LIMIT 1"
                ),
                {"o": org, "n": max(0, self.employee_count - 21)},
            ).one()
            queries = {
                "v1 employee page (offset 0)": (
                    "SELECT * FROM employees WHERE organization_id = :o AND archived_at IS NULL "
                    "ORDER BY last_name, first_name, id LIMIT 20 OFFSET 0",
                    {},
                ),
                "v1 employee page (last page, offset)": (
                    "SELECT * FROM employees WHERE organization_id = :o AND archived_at IS NULL "
                    "ORDER BY last_name, first_name, id LIMIT 20 OFFSET :off",
                    {"off": max(0, self.employee_count - 20)},
                ),
                "v1 employee total (count)": (
                    "SELECT count(*) FROM employees WHERE organization_id = :o "
                    "AND archived_at IS NULL",
                    {},
                ),
                "v2 employee page (last page, keyset)": (
                    "SELECT * FROM employees WHERE organization_id = :o AND archived_at IS NULL "
                    "AND (last_name, first_name, id) > (:l, :f, CAST(:i AS uuid)) "
                    "ORDER BY last_name, first_name, id LIMIT 21",
                    {"l": boundary[0], "f": boundary[1], "i": str(boundary[2])},
                ),
                "employee search (substring)": (
                    "SELECT * FROM employees WHERE organization_id = :o AND archived_at IS NULL "
                    "AND ((first_name || ' ' || last_name) ILIKE :p OR email ILIKE :p "
                    "OR employee_number ILIKE :p) ORDER BY last_name, first_name, id LIMIT 20",
                    {"p": "%person4%"},
                ),
                "events page (newest first)": (
                    "SELECT * FROM integration_events WHERE organization_id = :o "
                    "ORDER BY created_at DESC, id LIMIT 20",
                    {},
                ),
                "summary: processing percentiles (24 h)": (
                    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM "
                    "completed_at - created_at)), percentile_cont(0.95) WITHIN GROUP (ORDER BY "
                    "extract(epoch FROM completed_at - created_at)) FROM integration_events "
                    "WHERE organization_id = :o AND status = 'completed' "
                    "AND completed_at >= now() - interval '24 hours'",
                    {},
                ),
            }
            results: dict[str, Any] = {}
            for name, (sql, params) in queries.items():
                times, plan = [], None
                for _ in range(5):
                    row = conn.execute(
                        text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"),
                        {"o": org, **params},
                    ).scalar_one()
                    plan = row[0]
                    times.append(plan["Execution Time"])
                plan_text = json.dumps(plan["Plan"])
                nodes = _node_types(plan["Plan"])
                results[name] = {
                    "execution_ms_median": round(statistics.median(times), 3),
                    "uses_index": any("Index" in n for n in nodes),
                    "nodes": nodes,
                    "rows_read": _rows_read(plan["Plan"]),
                    "plan": plan_text,
                }
                print(
                    f"  {name:42} {results[name]['execution_ms_median']:8.3f} ms  "
                    f"{' > '.join(nodes[:4])}"
                )
        return version, results

    @property
    def employee_count(self) -> int:
        return self.call("GET", "/employees", params={"limit": 1}).json()["total"]


def _print_latency(name: str, stats: dict[str, float]) -> None:
    print(f"  {name:42} p50 {stats['p50_ms']:7.2f} ms   p95 {stats['p95_ms']:7.2f} ms")


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _node_types(plan: dict[str, Any]) -> list[str]:
    nodes = [plan["Node Type"] + (f" ({plan['Index Name']})" if "Index Name" in plan else "")]
    for child in plan.get("Plans", []):
        nodes.extend(_node_types(child))
    return nodes


def _rows_read(plan: dict[str, Any]) -> int:
    """Rows produced by scan nodes: what the query had to touch."""
    own = plan.get("Actual Rows", 0) if "Scan" in plan["Node Type"] else 0
    return own + sum(_rows_read(child) for child in plan.get("Plans", []))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--employees", type=int, default=1000)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--hires", type=int, default=100)
    parser.add_argument("--output", default="benchmark-results.json")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="How many Celery worker processes you started (recorded in the report).",
    )
    args = parser.parse_args()

    bench = Bench(args.api)
    print(f"Setting up an organization with {args.employees} employees...")
    bench.setup(args.employees)
    print(f"\n1. API latency ({args.requests} sequential requests per endpoint)")
    latency = bench.latency(args.requests)
    workers = f"{args.workers} worker" + ("s" if args.workers != 1 else "")
    print(f"\n2. Event throughput ({args.hires} hires, 3 external calls each, {workers})")
    throughput = bench.throughput(args.hires)
    print("\n3. Query plans (EXPLAIN ANALYZE, median of 5)")
    db_version, plans = bench.plans()

    report = {
        "environment": environment(db_version),
        "parameters": {
            "employees": args.employees,
            "requests_per_endpoint": args.requests,
            "hires": args.hires,
            "workers": args.workers,
            "organization_id": bench.org_id,
        },
        "latency": latency,
        "throughput": throughput,
        "query_plans": plans,
    }
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    env = report["environment"]
    print(
        f"\nEnvironment: {env['os']}; {env['cpu']} ({env['logical_cpus']} logical CPUs, "
        f"{env['memory_gb']} GB); Python {env['python']}; PostgreSQL {env['postgresql']}"
    )
    print(f"Full results: {args.output}")


if __name__ == "__main__":
    main()
