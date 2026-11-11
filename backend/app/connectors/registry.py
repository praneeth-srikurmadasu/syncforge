"""Connector registry and factory.

Adapters register themselves with `@register`. The rest of the application asks the
registry for a connector by type ("slack") and never imports adapter classes directly.
"""

from typing import Any

import httpx2 as httpx
from pydantic import ValidationError

from app.connectors.base import Connector, ConnectorSpec
from app.connectors.errors import ConnectorError, ErrorCategory
from app.connectors.http import ConnectorHttpClient
from app.core.config import Settings, get_settings

_REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    connector_type = cls.spec.connector_type
    if connector_type in _REGISTRY and _REGISTRY[connector_type] is not cls:
        raise ValueError(f"Connector type '{connector_type}' is already registered.")
    _REGISTRY[connector_type] = cls
    return cls


def get_connector_class(connector_type: str) -> type[Connector] | None:
    return _REGISTRY.get(connector_type)


def catalog() -> list[ConnectorSpec]:
    return sorted((cls.spec for cls in _REGISTRY.values()), key=lambda s: s.display_name)


class ConnectorConfigurationError(Exception):
    """Config or credentials do not match the connector's schema."""

    def __init__(self, field: str, errors: list[dict[str, str]]) -> None:
        super().__init__(f"Invalid {field}.")
        self.field = field
        self.errors = errors


def validation_details(field: str, exc: ValidationError) -> list[dict[str, str]]:
    # Field names and reasons only - never the submitted values (they may be secrets).
    return [
        {
            "field": ".".join([field, *(str(part) for part in err["loc"])]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]


def validate_settings(
    spec: ConnectorSpec, config: dict[str, Any], credentials: dict[str, Any] | None
) -> None:
    """Raise ConnectorConfigurationError if config/credentials do not fit the spec."""
    try:
        spec.config_model.model_validate(config)
    except ValidationError as exc:
        raise ConnectorConfigurationError("config", validation_details("config", exc)) from exc
    if credentials is not None:
        try:
            spec.credentials_model.model_validate(credentials)
        except ValidationError as exc:
            raise ConnectorConfigurationError(
                "credentials", validation_details("credentials", exc)
            ) from exc


def build_connector(
    connector_type: str,
    *,
    version: str,
    config: dict[str, Any],
    credentials: dict[str, Any],
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Connector:
    """Instantiate a ready-to-use adapter. Raises ConnectorError(CONFIGURATION) on problems."""
    settings = settings or get_settings()
    cls = get_connector_class(connector_type)
    if cls is None:
        raise ConnectorError(
            ErrorCategory.CONFIGURATION,
            f"Unknown connector type '{connector_type}'.",
            "unknown_connector_type",
        )
    spec = cls.spec
    if int(version.split(".", 1)[0]) != spec.major_version:
        raise ConnectorError(
            ErrorCategory.CONFIGURATION,
            f"Connector was configured with version {version}; installed adapter is "
            f"{spec.version}. Re-create the connector.",
            "connector_version_unsupported",
        )
    try:
        parsed_config = spec.config_model.model_validate(config)
        parsed_credentials = spec.credentials_model.model_validate(credentials)
    except ValidationError as exc:
        raise ConnectorError(
            ErrorCategory.CONFIGURATION,
            "Stored connector settings are invalid.",
            "invalid_settings",
        ) from exc

    base_url = (
        str(parsed_config.base_url)
        if parsed_config.base_url
        else getattr(settings, spec.default_base_url_setting)
    )
    http = ConnectorHttpClient(
        base_url,
        allowed_hosts=settings.connector_allowed_hosts,
        connect_timeout=settings.connector_connect_timeout_seconds,
        read_timeout=settings.connector_read_timeout_seconds,
        transport=transport,
    )
    return cls(config=parsed_config, credentials=parsed_credentials, http=http)
