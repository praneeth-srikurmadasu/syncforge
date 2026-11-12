"""Connector endpoints.

  GET  /api/v1/connector-types                                   catalog (any user)
  /api/v1/organizations/{organization_id}/connectors/...         organization-scoped

Credentials go in, never out. Connection tests and operations call the external
application synchronously (with the configured connect/read timeouts).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, require_org_permission
from app.connectors import registry
from app.core.config import Settings, get_settings
from app.models import CircuitState, Connector
from app.repositories.connectors import ConnectorRepository, ExternalAccountRepository
from app.schemas.common import Limit, Offset, Page
from app.schemas.connectors import (
    CircuitSummary,
    ConnectionTestResponse,
    ConnectorCreate,
    ConnectorErrorSummary,
    ConnectorResponse,
    ConnectorTypeResponse,
    ConnectorUpdate,
    CredentialSummary,
    ExternalAccountResponse,
    OperationRequest,
    OperationResponse,
)
from app.security.authorization import OrgContext, Permission
from app.services.connectors import ConnectorService

OPERATIONS = ["test_connection", "create_user", "update_user", "deactivate_user", "get_user"]

catalog_router = APIRouter(tags=["connectors"])
router = APIRouter(prefix="/organizations/{organization_id}/connectors", tags=["connectors"])

CanReadConnectors = Annotated[
    OrgContext, Depends(require_org_permission(Permission.CONNECTORS_READ))
]
CanManageConnectors = Annotated[
    OrgContext, Depends(require_org_permission(Permission.CONNECTORS_MANAGE))
]


def get_connector_settings() -> Settings:
    """Overridable in tests to point connectors at the mock services."""
    return get_settings()


ConnectorSettings = Annotated[Settings, Depends(get_connector_settings)]

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Member, but role lacks the required permission"},
    404: {"description": "Organization or connector not found, or caller is not a member"},
}


def _response(connector: Connector) -> ConnectorResponse:
    cls = registry.get_connector_class(connector.connector_type)
    credential = connector.credential
    return ConnectorResponse(
        id=connector.id,
        connector_type=connector.connector_type,
        name=connector.name,
        version=connector.connector_version,
        simulated=bool(cls and cls.spec.simulated),
        config=connector.config,
        status=connector.status,
        last_tested_at=connector.last_tested_at,
        last_error=(
            ConnectorErrorSummary(
                category=connector.last_error_category,
                message=connector.last_error_message or "",
            )
            if connector.last_error_category
            else None
        ),
        credentials=(
            CredentialSummary(
                auth_type=credential.auth_type,
                fingerprint=credential.fingerprint,
                updated_at=credential.updated_at,
            )
            if credential
            else None
        ),
        circuit=CircuitSummary(
            state=connector.circuit.state if connector.circuit else CircuitState.CLOSED,
            consecutive_failures=connector.circuit.consecutive_failures if connector.circuit else 0,
            open_until=connector.circuit.open_until if connector.circuit else None,
        ),
        created_at=connector.created_at,
        updated_at=connector.updated_at,
    )


@catalog_router.get("/connector-types", response_model=list[ConnectorTypeResponse])
def list_connector_types(_user: CurrentUser) -> list[ConnectorTypeResponse]:
    """Every connector type SyncForge can configure, with its config and credential schemas."""
    return [
        ConnectorTypeResponse(
            connector_type=spec.connector_type,
            display_name=spec.display_name,
            version=spec.version,
            description=spec.description,
            auth_type=spec.auth_type,
            simulated=spec.simulated,
            operations=OPERATIONS,
            config_schema=spec.config_model.model_json_schema(),
            credentials_schema=spec.credentials_model.model_json_schema(),
        )
        for spec in registry.catalog()
    ]


@router.get("", response_model=Page[ConnectorResponse], responses=_ERRORS)
def list_connectors(
    access: CanReadConnectors, db: DbSession, limit: Limit = 20, offset: Offset = 0
) -> Page[ConnectorResponse]:
    connectors, total = ConnectorRepository(db).list(
        access.organization.id, limit=limit, offset=offset
    )
    return Page(items=[_response(c) for c in connectors], total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS
    | {
        409: {"description": "Connector name already used"},
        422: {"description": "Unknown type, invalid config/credentials, or disallowed host"},
        503: {"description": "Credential encryption is not configured"},
    },
)
def create_connector(
    payload: ConnectorCreate,
    access: CanManageConnectors,
    db: DbSession,
    settings: ConnectorSettings,
) -> ConnectorResponse:
    """Configure a connector. Credentials are encrypted; status starts as `pending`."""
    connector = ConnectorService(db, settings).create(
        access.organization,
        connector_type=payload.connector_type,
        name=payload.name,
        config=payload.config,
        credentials=payload.credentials,
    )
    return _response(connector)


@router.get("/{connector_id}", response_model=ConnectorResponse, responses=_ERRORS)
def get_connector(
    connector_id: uuid.UUID, access: CanReadConnectors, db: DbSession
) -> ConnectorResponse:
    return _response(ConnectorService(db).get(access.organization, connector_id))


@router.patch(
    "/{connector_id}",
    response_model=ConnectorResponse,
    responses=_ERRORS | {409: {"description": "Name taken"}, 422: {"description": "Invalid"}},
)
def update_connector(
    connector_id: uuid.UUID,
    payload: ConnectorUpdate,
    access: CanManageConnectors,
    db: DbSession,
    settings: ConnectorSettings,
) -> ConnectorResponse:
    """Rename, change config, or rotate credentials (which also reconnects)."""
    connector = ConnectorService(db, settings).update(
        access.organization,
        connector_id,
        name=payload.name,
        config=payload.config,
        credentials=payload.credentials,
    )
    return _response(connector)


@router.post("/{connector_id}/test", response_model=ConnectionTestResponse, responses=_ERRORS)
def test_connector(
    connector_id: uuid.UUID, access: CanManageConnectors, db: DbSession, settings: ConnectorSettings
) -> ConnectionTestResponse:
    """Call the external application with a cheap read-only request.

    Always `200` when the test ran: `ok` says whether it succeeded, `error` says why not.
    """
    result = ConnectorService(db, settings).test(access.organization, connector_id)
    return ConnectionTestResponse(**result.__dict__)


@router.post("/{connector_id}/disconnect", response_model=ConnectorResponse, responses=_ERRORS)
def disconnect_connector(
    connector_id: uuid.UUID, access: CanManageConnectors, db: DbSession
) -> ConnectorResponse:
    """Delete the stored credentials. Idempotent."""
    return _response(ConnectorService(db).disconnect(access.organization, connector_id))


@router.post(
    "/{connector_id}/operations",
    response_model=OperationResponse,
    responses=_ERRORS
    | {
        409: {"description": "Disconnected, already linked / not linked, or terminated"},
        422: {"description": "Unknown employee"},
        502: {"description": "The external application failed (normalized error in details)"},
    },
)
def run_operation(
    connector_id: uuid.UUID,
    payload: OperationRequest,
    access: CanManageConnectors,
    db: DbSession,
    settings: ConnectorSettings,
) -> OperationResponse:
    """Run one connector operation for one employee, now (manual sync).

    Workflows run the same operations automatically. Recorded in the audit log.
    """
    result = ConnectorService(db, settings).run_operation(
        access.organization,
        connector_id,
        operation=payload.operation,
        employee_id=payload.employee_id,
        audited=True,
    )
    return OperationResponse(**result.__dict__)


@router.get(
    "/{connector_id}/accounts", response_model=Page[ExternalAccountResponse], responses=_ERRORS
)
def list_accounts(
    connector_id: uuid.UUID,
    access: CanReadConnectors,
    db: DbSession,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[ExternalAccountResponse]:
    """Employees linked to accounts in this external application."""
    connector = ConnectorService(db).get(access.organization, connector_id)
    accounts, total = ExternalAccountRepository(db).list_for_connector(
        access.organization.id, connector.id, limit=limit, offset=offset
    )
    return Page(
        items=[ExternalAccountResponse.model_validate(a) for a in accounts],
        total=total,
        limit=limit,
        offset=offset,
    )
