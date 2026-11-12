"""Connector, credential and external-account data access (always organization-scoped)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Connector, ExternalAccount


class ConnectorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, organization_id: uuid.UUID, connector_id: uuid.UUID, *, for_update: bool = False
    ) -> Connector | None:
        query = (
            select(Connector)
            .where(Connector.organization_id == organization_id, Connector.id == connector_id)
            .options(selectinload(Connector.credential))
        )
        if for_update:
            query = query.with_for_update(of=Connector)
        return self.session.scalar(query)

    def name_taken(
        self, organization_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        query = select(Connector.id).where(
            Connector.organization_id == organization_id, Connector.name == name
        )
        if exclude_id is not None:
            query = query.where(Connector.id != exclude_id)
        return self.session.scalar(query) is not None

    def add(self, connector: Connector) -> Connector:
        self.session.add(connector)
        self.session.flush()
        return connector

    def list(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Connector], int]:
        condition = Connector.organization_id == organization_id
        total = self.session.scalar(select(func.count()).select_from(Connector).where(condition))
        items = self.session.scalars(
            select(Connector)
            .where(condition)
            .options(selectinload(Connector.credential))
            .order_by(Connector.name, Connector.id)
            .limit(limit)
            .offset(offset)
        )
        return list(items), total or 0


class ExternalAccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, connector_id: uuid.UUID, employee_id: uuid.UUID, *, for_update: bool = False
    ) -> ExternalAccount | None:
        query = select(ExternalAccount).where(
            ExternalAccount.connector_id == connector_id,
            ExternalAccount.employee_id == employee_id,
        )
        if for_update:
            query = query.with_for_update()
        return self.session.scalar(query)

    def add(self, account: ExternalAccount) -> ExternalAccount:
        self.session.add(account)
        self.session.flush()
        return account

    def list_for_connector(
        self, organization_id: uuid.UUID, connector_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[ExternalAccount], int]:
        conditions = (
            ExternalAccount.organization_id == organization_id,
            ExternalAccount.connector_id == connector_id,
        )
        total = self.session.scalar(
            select(func.count()).select_from(ExternalAccount).where(*conditions)
        )
        items = self.session.scalars(
            select(ExternalAccount)
            .where(*conditions)
            .order_by(ExternalAccount.created_at, ExternalAccount.id)
            .limit(limit)
            .offset(offset)
        )
        return list(items), total or 0
