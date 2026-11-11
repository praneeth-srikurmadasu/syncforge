"""Database rules for connectors, their credentials and external accounts."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Connector,
    ConnectorCredential,
    ConnectorStatus,
    ExternalAccount,
    ExternalAccountStatus,
    Organization,
)
from tests.factories import create_employee, create_organization


def make_connector(session: Session, org: Organization, name: str = "Slack") -> Connector:
    connector = Connector(
        organization_id=org.id, connector_type="slack", connector_version="1.0.0", name=name
    )
    session.add(connector)
    session.flush()
    return connector


def add_credential(session: Session, connector: Connector, org_id: uuid.UUID) -> None:
    session.add(
        ConnectorCredential(
            organization_id=org_id,
            connector_id=connector.id,
            auth_type="bearer_token",
            encrypted_secret="gAAAA-not-real",
            fingerprint="...abcd",
        )
    )
    session.flush()


def test_defaults(db_session: Session) -> None:
    connector = make_connector(db_session, create_organization(db_session))
    db_session.refresh(connector)

    assert connector.status is ConnectorStatus.PENDING
    assert connector.config == {}
    assert connector.credential is None


def test_name_is_unique_per_organization(db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    make_connector(db_session, acme)
    make_connector(db_session, globex)  # other organization: allowed

    with pytest.raises(IntegrityError, match="uq_connectors_organization_id_name"):
        make_connector(db_session, acme)


def test_credential_cannot_belong_to_another_organizations_connector(db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    globex_connector = make_connector(db_session, globex)

    with pytest.raises(
        IntegrityError, match="fk_connector_credentials_connector_same_organization"
    ):
        add_credential(db_session, globex_connector, acme.id)


def test_one_credential_set_per_connector(db_session: Session) -> None:
    org = create_organization(db_session)
    connector = make_connector(db_session, org)
    add_credential(db_session, connector, org.id)

    with pytest.raises(IntegrityError, match="uq_connector_credentials_connector_id"):
        add_credential(db_session, connector, org.id)


def test_deleting_a_connector_deletes_its_credentials(db_session: Session) -> None:
    org = create_organization(db_session)
    connector = make_connector(db_session, org)
    add_credential(db_session, connector, org.id)

    db_session.execute(text("DELETE FROM connectors WHERE id = :id"), {"id": connector.id})

    assert db_session.scalar(select(ConnectorCredential)) is None


def test_unknown_status_is_rejected(db_session: Session) -> None:
    org = create_organization(db_session)

    with pytest.raises(IntegrityError, match="ck_connectors_connector_status"):
        db_session.execute(
            text(
                "INSERT INTO connectors (id, organization_id, connector_type, connector_version, "
                "name, status) VALUES (:id, :org, 'slack', '1.0.0', 'X', 'broken')"
            ),
            {"id": uuid.uuid4(), "org": org.id},
        )


# ---- external accounts ---------------------------------------------------------------


def link(
    session: Session,
    org: Organization,
    connector: Connector,
    employee_id: uuid.UUID,
    external_id: str = "U123",
    org_id: uuid.UUID | None = None,
) -> ExternalAccount:
    account = ExternalAccount(
        organization_id=org_id or org.id,
        connector_id=connector.id,
        employee_id=employee_id,
        external_id=external_id,
    )
    session.add(account)
    session.flush()
    return account


def test_external_account_defaults(db_session: Session) -> None:
    org = create_organization(db_session)
    account = link(
        db_session, org, make_connector(db_session, org), create_employee(db_session, org).id
    )
    db_session.refresh(account)

    assert account.status is ExternalAccountStatus.ACTIVE
    assert account.last_synced_at is None


def test_one_account_per_connector_and_employee(db_session: Session) -> None:
    org = create_organization(db_session)
    connector = make_connector(db_session, org)
    employee = create_employee(db_session, org)
    link(db_session, org, connector, employee.id, "U1")

    with pytest.raises(IntegrityError, match="uq_external_accounts_connector_id_employee_id"):
        link(db_session, org, connector, employee.id, "U2")


def test_external_id_maps_to_one_employee_per_connector(db_session: Session) -> None:
    org = create_organization(db_session)
    connector = make_connector(db_session, org)
    link(db_session, org, connector, create_employee(db_session, org).id, "U1")

    with pytest.raises(IntegrityError, match="uq_external_accounts_connector_id_external_id"):
        link(db_session, org, connector, create_employee(db_session, org).id, "U1")


def test_external_account_cannot_mix_organizations(db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    acme_connector = make_connector(db_session, acme)
    globex_employee = create_employee(db_session, globex)

    with pytest.raises(IntegrityError, match="fk_external_accounts_employee_same_organization"):
        link(db_session, acme, acme_connector, globex_employee.id)


def test_deleting_a_connector_deletes_its_external_accounts(db_session: Session) -> None:
    org = create_organization(db_session)
    connector = make_connector(db_session, org)
    link(db_session, org, connector, create_employee(db_session, org).id)

    db_session.execute(text("DELETE FROM connectors WHERE id = :id"), {"id": connector.id})

    assert db_session.scalar(select(ExternalAccount)) is None
