"""Local mock versions of the external applications SyncForge integrates with.

These are SIMULATIONS for development and testing. They follow the shape of the real
APIs closely enough to exercise the connectors (Slack SCIM, Google Admin SDK Directory,
a REST payroll API) but they are not the real services and keep data in memory only.

Every mock also exposes /_mock/* control endpoints to inject failures on demand.
"""
