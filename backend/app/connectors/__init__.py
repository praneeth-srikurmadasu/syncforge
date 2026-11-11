"""Connector framework: one interface, one adapter per external application.

Adapters register themselves with `app.connectors.registry.register`. Importing this
package imports every built-in adapter, so the registry is always complete.
"""

from app.connectors import google_workspace, payroll, slack  # noqa: F401 - registers adapters
