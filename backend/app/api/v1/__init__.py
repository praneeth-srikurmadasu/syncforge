"""Version 1 of the public REST API, mounted at /api/v1."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.departments import router as departments_router
from app.api.v1.employees import router as employees_router
from app.api.v1.organizations import router as organizations_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(organizations_router)
api_router.include_router(departments_router)
api_router.include_router(employees_router)
