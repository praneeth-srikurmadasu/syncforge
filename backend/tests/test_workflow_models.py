"""Database rules for workflows, steps, executions and synchronization jobs."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ExecutionStatus,
    IntegrationEvent,
    JobStatus,
    Organization,
    SynchronizationJob,
    Workflow,
    WorkflowExecution,
    WorkflowStep,
)
from tests.factories import create_connector, create_employee, create_organization


def make_workflow(
    session: Session, org: Organization, name: str = "Onboarding", trigger: str = "employee.created"
) -> Workflow:
    workflow = Workflow(organization_id=org.id, name=name, trigger_event_type=trigger)
    session.add(workflow)
    session.flush()
    return workflow


def make_event(session: Session, org: Organization) -> IntegrationEvent:
    employee = create_employee(session, org)
    event = IntegrationEvent(
        organization_id=org.id, event_type="employee.created", employee_id=employee.id, payload={}
    )
    session.add(event)
    session.flush()
    return event


def test_workflow_defaults_and_ordered_steps(db_session: Session) -> None:
    org = create_organization(db_session)
    slack = create_connector(db_session, org, connector_type="slack")
    payroll = create_connector(db_session, org, connector_type="payroll")
    workflow = make_workflow(db_session, org)
    workflow.steps = [
        WorkflowStep(
            organization_id=org.id, position=2, connector_id=payroll.id, operation="create_user"
        ),
        WorkflowStep(
            organization_id=org.id, position=1, connector_id=slack.id, operation="create_user"
        ),
    ]
    db_session.flush()
    db_session.expire_all()

    loaded = db_session.scalar(select(Workflow).where(Workflow.id == workflow.id))
    assert loaded.is_active is False  # new workflows never run until activated
    assert loaded.version == 1
    assert [s.position for s in loaded.steps] == [1, 2]
    assert loaded.steps[0].connector_id == slack.id


def test_workflow_names_are_unique_per_organization(db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    make_workflow(db_session, acme)
    make_workflow(db_session, globex)

    with pytest.raises(IntegrityError, match="uq_workflows_organization_id_name"):
        make_workflow(db_session, acme)


def test_trigger_must_be_a_known_event_type(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_workflows_trigger"):
        make_workflow(db_session, create_organization(db_session), trigger="employee.promoted")


@pytest.mark.parametrize(
    ("position", "operation", "constraint"),
    [
        (0, "create_user", "ck_workflow_steps_position_positive"),
        (1, "get_user", "ck_workflow_steps_operation"),  # reads are not workflow actions
    ],
)
def test_step_values_are_constrained(
    db_session: Session, position: int, operation: str, constraint: str
) -> None:
    org = create_organization(db_session)
    workflow = make_workflow(db_session, org)
    db_session.add(
        WorkflowStep(
            organization_id=org.id,
            workflow_id=workflow.id,
            position=position,
            connector_id=create_connector(db_session, org).id,
            operation=operation,
        )
    )
    with pytest.raises(IntegrityError, match=constraint):
        db_session.flush()


def test_step_positions_are_unique_within_a_workflow(db_session: Session) -> None:
    org = create_organization(db_session)
    workflow = make_workflow(db_session, org)
    connector = create_connector(db_session, org)
    for _ in range(2):
        db_session.add(
            WorkflowStep(
                organization_id=org.id,
                workflow_id=workflow.id,
                position=1,
                connector_id=connector.id,
                operation="create_user",
            )
        )
    with pytest.raises(IntegrityError, match="uq_workflow_steps_workflow_id_position"):
        db_session.flush()


def test_a_step_cannot_use_another_organizations_connector(db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    workflow = make_workflow(db_session, acme)
    db_session.add(
        WorkflowStep(
            organization_id=acme.id,
            workflow_id=workflow.id,
            position=1,
            connector_id=create_connector(db_session, globex).id,
            operation="create_user",
        )
    )
    db_session.flush()
    # The connector check is deferred to commit (see the model); force it now.
    with pytest.raises(IntegrityError, match="fk_workflow_steps_connector_same_organization"):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_a_connector_used_by_a_workflow_cannot_be_deleted(db_session: Session) -> None:
    org = create_organization(db_session)
    connector = create_connector(db_session, org)
    workflow = make_workflow(db_session, org)
    db_session.add(
        WorkflowStep(
            organization_id=org.id,
            workflow_id=workflow.id,
            position=1,
            connector_id=connector.id,
            operation="create_user",
        )
    )
    db_session.flush()

    db_session.execute(text("DELETE FROM connectors WHERE id = :id"), {"id": connector.id})
    # The check is deferred to commit; force it now.
    with pytest.raises(IntegrityError, match="fk_workflow_steps_connector_same_organization"):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_deleting_an_organization_removes_its_workflows_and_history(db_session: Session) -> None:
    org = create_organization(db_session)
    connector = create_connector(db_session, org)
    workflow = make_workflow(db_session, org)
    workflow.steps = [
        WorkflowStep(
            organization_id=org.id, position=1, connector_id=connector.id, operation="create_user"
        )
    ]
    event = make_event(db_session, org)
    execution = WorkflowExecution(
        organization_id=org.id, event_id=event.id, workflow_id=workflow.id, workflow_version=1
    )
    db_session.add(execution)
    db_session.flush()

    db_session.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org.id})

    for table in ("workflows", "workflow_steps", "workflow_executions", "integration_events"):
        assert db_session.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0  # noqa: S608


def test_one_execution_per_event_and_workflow(db_session: Session) -> None:
    org = create_organization(db_session)
    workflow = make_workflow(db_session, org)
    event = make_event(db_session, org)
    first = WorkflowExecution(
        organization_id=org.id, event_id=event.id, workflow_id=workflow.id, workflow_version=1
    )
    db_session.add(first)
    db_session.flush()
    db_session.refresh(first)
    assert first.status is ExecutionStatus.RUNNING

    db_session.add(
        WorkflowExecution(
            organization_id=org.id, event_id=event.id, workflow_id=workflow.id, workflow_version=1
        )
    )
    with pytest.raises(IntegrityError, match="uq_workflow_executions_event_id_workflow_id"):
        db_session.flush()


def test_jobs_are_ordered_unique_and_stay_in_the_organization(db_session: Session) -> None:
    org, other = create_organization(db_session), create_organization(db_session)
    workflow = make_workflow(db_session, org)
    event = make_event(db_session, org)
    execution = WorkflowExecution(
        organization_id=org.id, event_id=event.id, workflow_id=workflow.id, workflow_version=1
    )
    db_session.add(execution)
    db_session.flush()
    connector = create_connector(db_session, org)
    job = SynchronizationJob(
        organization_id=org.id,
        execution_id=execution.id,
        position=1,
        connector_id=connector.id,
        operation="create_user",
        employee_id=event.employee_id,
    )
    db_session.add(job)
    db_session.flush()
    db_session.refresh(job)
    assert (job.status, job.attempts) == (JobStatus.PENDING, 0)

    db_session.add(
        SynchronizationJob(
            organization_id=org.id,
            execution_id=execution.id,
            position=2,
            connector_id=create_connector(db_session, other).id,  # another organization's
            operation="create_user",
            employee_id=event.employee_id,
        )
    )
    with pytest.raises(IntegrityError, match="fk_synchronization_jobs_connector_same_organization"):
        db_session.flush()
