"""Run the mock external services (mock-services/) as real HTTP servers during tests.

Each mock runs in a background thread under uvicorn on a free port, so connector tests
exercise real sockets: real timeouts, real connection errors, real HTTP status codes.
"""

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import uvicorn

MOCK_SERVICES_DIR = Path(__file__).resolve().parents[2] / "mock-services"
if str(MOCK_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(MOCK_SERVICES_DIR))

from mockservices import google_workspace, payroll, slack  # noqa: E402

# Default credentials each mock accepts (local, fake values).
MOCK_CREDENTIALS: dict[str, dict[str, str]] = {
    "slack": {"token": slack.TOKEN},
    "google_workspace": {
        "client_id": google_workspace.CLIENT_ID,
        "client_secret": google_workspace.CLIENT_SECRET,
    },
    "payroll": {"api_key": payroll.API_KEY},
}
MODULES: dict[str, ModuleType] = {
    "slack": slack,
    "google_workspace": google_workspace,
    "payroll": payroll,
}


@dataclass
class RunningMock:
    module: ModuleType
    base_url: str

    @property
    def state(self) -> Any:
        return self.module.state

    def reset(self) -> None:
        self.module.state.reset()
        if self.module is google_workspace:
            google_workspace.tokens.clear()


class _ThreadedServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # not allowed outside the main thread
        pass


def start(module: ModuleType) -> tuple[_ThreadedServer, threading.Thread, RunningMock]:
    config = uvicorn.Config(
        module.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"
    )
    server = _ThreadedServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"mock server {module.__name__} did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, RunningMock(module=module, base_url=f"http://127.0.0.1:{port}")
