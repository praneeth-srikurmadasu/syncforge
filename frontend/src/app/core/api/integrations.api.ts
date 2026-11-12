import { HttpClient, HttpResourceRequest } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_BASE, PageQuery, orgUrl, query } from './http-util';
import {
  ConnectionTest,
  Connector,
  ConnectorCreate,
  ConnectorUpdate,
  OperationRequest,
  OperationResponse,
  Page,
  ReconcileResult,
  Workflow,
  WorkflowCreate,
  WorkflowUpdate,
  ExecutionStatus,
  Execution,
} from './models';

@Injectable({ providedIn: 'root' })
export class ConnectorsApi {
  private readonly http = inject(HttpClient);

  /** The catalog of connector types (a plain array, not a page). */
  typesRequest(): HttpResourceRequest {
    return { url: `${API_BASE}/connector-types` };
  }

  get(orgId: string, id: string): Observable<Connector> {
    return this.http.get<Connector>(orgUrl(orgId, 'connectors', id));
  }

  listRequest(orgId: string, page: PageQuery = { limit: 100 }): HttpResourceRequest {
    return { url: orgUrl(orgId, 'connectors'), params: query(page) };
  }

  list(orgId: string, page: PageQuery = { limit: 100 }): Observable<Page<Connector>> {
    return this.http.get<Page<Connector>>(orgUrl(orgId, 'connectors'), {
      params: query(page),
    });
  }

  getRequest(orgId: string, id: string): HttpResourceRequest {
    return { url: orgUrl(orgId, 'connectors', id) };
  }

  create(orgId: string, body: ConnectorCreate): Observable<Connector> {
    return this.http.post<Connector>(orgUrl(orgId, 'connectors'), body);
  }

  update(orgId: string, id: string, body: ConnectorUpdate): Observable<Connector> {
    return this.http.patch<Connector>(orgUrl(orgId, 'connectors', id), body);
  }

  test(orgId: string, id: string): Observable<ConnectionTest> {
    return this.http.post<ConnectionTest>(orgUrl(orgId, 'connectors', id, 'test'), null);
  }

  disconnect(orgId: string, id: string): Observable<Connector> {
    return this.http.post<Connector>(orgUrl(orgId, 'connectors', id, 'disconnect'), null);
  }

  runOperation(orgId: string, id: string, body: OperationRequest): Observable<OperationResponse> {
    return this.http.post<OperationResponse>(orgUrl(orgId, 'connectors', id, 'operations'), body);
  }

  reconcile(orgId: string, id: string): Observable<ReconcileResult> {
    return this.http.post<ReconcileResult>(orgUrl(orgId, 'connectors', id, 'reconcile'), null);
  }

  accountsRequest(orgId: string, id: string, page: PageQuery): HttpResourceRequest {
    return { url: orgUrl(orgId, 'connectors', id, 'accounts'), params: query(page) };
  }
}

export interface WorkflowQuery extends PageQuery {
  trigger_event_type?: string;
  is_active?: boolean | null;
}

@Injectable({ providedIn: 'root' })
export class WorkflowsApi {
  private readonly http = inject(HttpClient);

  listRequest(orgId: string, q: WorkflowQuery): HttpResourceRequest {
    return { url: orgUrl(orgId, 'workflows'), params: query(q) };
  }

  list(orgId: string, q: WorkflowQuery): Observable<Page<Workflow>> {
    return this.http.get<Page<Workflow>>(orgUrl(orgId, 'workflows'), { params: query(q) });
  }

  getRequest(orgId: string, id: string): HttpResourceRequest {
    return { url: orgUrl(orgId, 'workflows', id) };
  }

  get(orgId: string, id: string): Observable<Workflow> {
    return this.http.get<Workflow>(orgUrl(orgId, 'workflows', id));
  }

  create(orgId: string, body: WorkflowCreate): Observable<Workflow> {
    return this.http.post<Workflow>(orgUrl(orgId, 'workflows'), body);
  }

  update(orgId: string, id: string, body: WorkflowUpdate): Observable<Workflow> {
    return this.http.patch<Workflow>(orgUrl(orgId, 'workflows', id), body);
  }

  setActive(orgId: string, id: string, active: boolean): Observable<Workflow> {
    const action = active ? 'activate' : 'deactivate';
    return this.http.post<Workflow>(orgUrl(orgId, 'workflows', id, action), null);
  }

  executionsRequest(
    orgId: string,
    id: string,
    q: PageQuery & { execution_status?: ExecutionStatus | '' },
  ): HttpResourceRequest {
    return { url: orgUrl(orgId, 'workflows', id, 'executions'), params: query(q) };
  }

  executions(orgId: string, id: string, q: PageQuery): Observable<Page<Execution>> {
    return this.http.get<Page<Execution>>(orgUrl(orgId, 'workflows', id, 'executions'), {
      params: query(q),
    });
  }
}
