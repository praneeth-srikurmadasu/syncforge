import { HttpClient, HttpResourceRequest } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { PageQuery, orgUrl, query } from './http-util';
import {
  AuditEntry,
  AuditOutcome,
  ConflictDetail,
  ConflictField,
  ConflictSeverity,
  ConflictStatus,
  DeadLetter,
  DeadLetterStatus,
  IntegrationEvent,
  IntegrationEventStatus,
  Page,
  Policy,
  PolicyUpdate,
  ResolveRequest,
  Conflict,
} from './models';

export interface EventQuery extends PageQuery {
  event_status?: IntegrationEventStatus | '';
  event_type?: string;
  employee_id?: string;
}

export interface DeadLetterQuery extends PageQuery {
  entry_status?: DeadLetterStatus | '';
  connector_id?: string;
}

export interface ConflictQuery extends PageQuery {
  conflict_status?: ConflictStatus | '';
  severity?: ConflictSeverity | '';
  field?: ConflictField | '';
  employee_id?: string;
  connector_id?: string;
}

export interface AuditQuery extends PageQuery {
  action?: string;
  resource_type?: string;
  resource_id?: string;
  actor_user_id?: string;
  outcome?: AuditOutcome | '';
  since?: string;
  until?: string;
}

const params = query;

@Injectable({ providedIn: 'root' })
export class EventsApi {
  private readonly http = inject(HttpClient);

  listRequest(orgId: string, q: EventQuery): HttpResourceRequest {
    return { url: orgUrl(orgId, 'events'), params: params(q) };
  }

  list(orgId: string, q: EventQuery): Observable<Page<IntegrationEvent>> {
    return this.http.get<Page<IntegrationEvent>>(orgUrl(orgId, 'events'), { params: params(q) });
  }

  getRequest(orgId: string, id: string): HttpResourceRequest {
    return { url: orgUrl(orgId, 'events', id) };
  }

  attemptsRequest(orgId: string, id: string): HttpResourceRequest {
    return { url: orgUrl(orgId, 'events', id, 'attempts') };
  }
}

@Injectable({ providedIn: 'root' })
export class DeadLettersApi {
  private readonly http = inject(HttpClient);

  listRequest(orgId: string, q: DeadLetterQuery): HttpResourceRequest {
    return { url: orgUrl(orgId, 'dead-letter-events'), params: params(q) };
  }

  list(orgId: string, q: DeadLetterQuery): Observable<Page<DeadLetter>> {
    return this.http.get<Page<DeadLetter>>(orgUrl(orgId, 'dead-letter-events'), {
      params: params(q),
    });
  }

  getRequest(orgId: string, id: string): HttpResourceRequest {
    return { url: orgUrl(orgId, 'dead-letter-events', id) };
  }

  replay(orgId: string, id: string): Observable<DeadLetter> {
    return this.http.post<DeadLetter>(orgUrl(orgId, 'dead-letter-events', id, 'replay'), null);
  }
}

@Injectable({ providedIn: 'root' })
export class ConflictsApi {
  private readonly http = inject(HttpClient);

  listRequest(orgId: string, q: ConflictQuery): HttpResourceRequest {
    return { url: orgUrl(orgId, 'conflicts'), params: params(q) };
  }

  list(orgId: string, q: ConflictQuery): Observable<Page<Conflict>> {
    return this.http.get<Page<Conflict>>(orgUrl(orgId, 'conflicts'), { params: params(q) });
  }

  getRequest(orgId: string, id: string): HttpResourceRequest {
    return { url: orgUrl(orgId, 'conflicts', id) };
  }

  resolve(orgId: string, id: string, body: ResolveRequest): Observable<ConflictDetail> {
    return this.http.post<ConflictDetail>(orgUrl(orgId, 'conflicts', id, 'resolve'), body);
  }

  policiesRequest(orgId: string): HttpResourceRequest {
    return { url: orgUrl(orgId, 'data-source-policies') };
  }

  updatePolicy(orgId: string, field: ConflictField, body: PolicyUpdate): Observable<Policy> {
    return this.http.put<Policy>(orgUrl(orgId, 'data-source-policies', field), body);
  }
}

@Injectable({ providedIn: 'root' })
export class AuditApi {
  private readonly http = inject(HttpClient);

  listRequest(orgId: string, q: AuditQuery): HttpResourceRequest {
    return { url: orgUrl(orgId, 'audit-logs'), params: params(q) };
  }

  list(orgId: string, q: AuditQuery): Observable<Page<AuditEntry>> {
    return this.http.get<Page<AuditEntry>>(orgUrl(orgId, 'audit-logs'), { params: params(q) });
  }
}
