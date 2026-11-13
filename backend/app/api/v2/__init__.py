"""Version 2 of the public REST API, mounted at /api/v2.

v2 holds only the endpoints whose contract changed in a breaking way; everything else is
served by v1, which stays supported. See docs/api.md (Versioning).
"""

from fastapi import APIRouter

from app.api.v2.employees import router as employees_router

api_router_v2 = APIRouter(prefix="/api/v2")
api_router_v2.include_router(employees_router)
