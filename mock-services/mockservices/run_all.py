"""Run all three mock services in one process (local development convenience).

From the mock-services folder:

    python -m mockservices.run_all

Slack on 9101, Google Workspace on 9102, payroll on 9103, all bound to 127.0.0.1.
Press Ctrl+C to stop. Each mock still has its own /_mock control API and /docs page.
"""

import asyncio

import uvicorn

from mockservices import google_workspace, payroll, slack

SERVICES = ((slack.app, 9101), (google_workspace.app, 9102), (payroll.app, 9103))


async def _serve() -> None:
    servers = [
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info"))
        for app, port in SERVICES
    ]
    await asyncio.gather(*(server.serve() for server in servers))


def main() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
