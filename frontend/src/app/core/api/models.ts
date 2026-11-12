// Friendly names for the generated OpenAPI types (schema.d.ts is regenerated from the
// backend with `npm run api:types`; never edit it by hand).
import type { components } from './schema';

type S = components['schemas'];

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type TokenResponse = S['TokenResponse'];
export type Me = S['MeResponse'];
export type MembershipSummary = S['MembershipSummary'];
export type UserResponse = S['UserResponse'];
export type OwnSecurityEvent = S['OwnSecurityEventResponse'];
export type RegisterRequest = S['RegisterRequest'];
export type OrganizationRole = S['OrganizationRole'];
export type Organization = S['OrganizationResponse'];
export type Member = S['MemberResponse'];
export type Department = S['DepartmentResponse'];
export type DepartmentRef = S['DepartmentRef'];
export type ManagerRef = S['ManagerRef'];
export type Employee = S['EmployeeResponse'];
export type EmployeeCreate = S['EmployeeCreate'];
export type EmployeeUpdate = S['EmployeeUpdate'];
export type EmployeeSort = S['EmployeeSort'];
export type EmploymentStatus = S['EmploymentStatus'];
export type ConnectorType = S['ConnectorTypeResponse'];
export type Connector = S['ConnectorResponse'];
export type ConnectorCreate = S['ConnectorCreate'];
export type ConnectorUpdate = S['ConnectorUpdate'];
export type ConnectorStatus = S['ConnectorStatus'];
export type CircuitState = S['CircuitState'];
export type ConnectionTest = S['ConnectionTestResponse'];
export type ExternalAccount = S['ExternalAccountResponse'];
export type OperationRequest = S['OperationRequest'];
export type OperationResponse = S['OperationResponse'];
export type ReconcileResult = S['ReconcileResponse'];
export type Workflow = S['WorkflowResponse'];
export type WorkflowCreate = S['WorkflowCreate'];
export type WorkflowUpdate = S['WorkflowUpdate'];
export type StepInput = S['StepInput'];
export type StepOperation = S['StepOperation'];
export type StepResponse = S['StepResponse'];
export type Execution = S['ExecutionResponse'];
export type ExecutionStatus = S['ExecutionStatus'];
export type Job = S['JobResponse'];
export type JobStatus = S['JobStatus'];
export type IntegrationEvent = S['EventResponse'];
export type IntegrationEventDetail = S['EventDetailResponse'];
export type IntegrationEventStatus = S['IntegrationEventStatus'];
export type Attempt = S['AttemptResponse'];
export type DeadLetter = S['DeadLetterResponse'];
export type DeadLetterDetail = S['DeadLetterDetailResponse'];
export type DeadLetterStatus = S['DeadLetterStatus'];
export type Policy = S['PolicyResponse'];
export type PolicyUpdate = S['PolicyUpdate'];
export type ConflictField = S['PolicyResponse']['field'];
export type Conflict = S['ConflictResponse'];
export type ConflictDetail = S['ConflictDetailResponse'];
export type ConflictSeverity = S['ConflictSeverity'];
export type ConflictStatus = S['ConflictStatus'];
export type ResolveRequest = S['ResolveRequest'];
export type AuditEntry = S['AuditLogResponse'];
export type AuditOutcome = S['AuditOutcome'];

export const EVENT_TYPES = [
  'employee.created',
  'employee.updated',
  'employee.department_changed',
  'employee.manager_changed',
  'employee.terminated',
] as const satisfies readonly WorkflowCreate['trigger_event_type'][];
export type EventType = (typeof EVENT_TYPES)[number];
