import { Injectable, inject } from '@angular/core';
import { Observable, catchError, forkJoin, map, of } from 'rxjs';
import { ApiError } from '../../core/api/api-error';
import { ConnectorsApi, WorkflowsApi } from '../../core/api/integrations.api';
import { AuditApi, ConflictsApi, DeadLettersApi, EventsApi } from '../../core/api/operations.api';
import { Connector, IntegrationEventStatus } from '../../core/api/models';
import { EmployeesApi } from '../../core/api/workforce.api';
import { DepartmentsApi } from '../../core/api/workforce.api';
import { Department } from '../../core/api/models';

/** A number from the API, or the error that prevented reading it (shown, never hidden). */
export type Count = number | ApiError;

export const EVENT_STATUSES: IntegrationEventStatus[] = [
  'pending',
  'processing',
  'retrying',
  'completed',
  'dead_letter',
];

export interface Overview {
  employeesActive: Count;
  employeesOnLeave: Count;
  employeesTerminated: Count;
  workflowsActive: Count;
  workflowsTotal: Count;
  events: Record<IntegrationEventStatus, Count>;
  deadLettersOpen: Count;
  conflictsOpen: Count;
  conflictsBySeverity: Record<'low' | 'medium' | 'high' | 'critical', Count>;
  connectors: Connector[] | ApiError;
}

export interface DailyActivity {
  days: string[]; // labels
  succeeded: number[];
  failed: number[];
  retries: number[];
}

/** Calendar-day windows (local time) ending today: [start, end) pairs as ISO strings. */
export function dayWindows(
  days: number,
  now = new Date(),
): { label: string; since: string; until: string }[] {
  const fmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric' });
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Array.from({ length: days }, (_, i) => {
    const start = new Date(startOfToday);
    start.setDate(start.getDate() - (days - 1 - i));
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    return { label: fmt.format(start), since: start.toISOString(), until: end.toISOString() };
  });
}

/**
 * Every dashboard figure comes from an existing list endpoint: totals are read with
 * `limit=1` (the response carries `total`), and daily activity from audit-log entries in
 * each day's window. The backend has no aggregate endpoints; nothing here is estimated.
 */
@Injectable({ providedIn: 'root' })
export class DashboardData {
  private readonly departments = inject(DepartmentsApi);
  private readonly employees = inject(EmployeesApi);
  private readonly connectors = inject(ConnectorsApi);
  private readonly workflows = inject(WorkflowsApi);
  private readonly events = inject(EventsApi);
  private readonly deadLetters = inject(DeadLettersApi);
  private readonly conflicts = inject(ConflictsApi);
  private readonly audit = inject(AuditApi);

  overview(orgId: string): Observable<Overview> {
    const one = { limit: 1 };
    const total = <T>(source: Observable<{ total: number } & T>): Observable<Count> =>
      source.pipe(
        map((page) => page.total),
        catchError((e: unknown) => of(ApiError.from(e))),
      );
    const workflowTotal = (active?: boolean) =>
      total(this.workflows.list(orgId, { limit: 1, is_active: active }));

    return forkJoin({
      employeesActive: total(this.employees.list(orgId, { ...one, employment_status: 'active' })),
      employeesOnLeave: total(
        this.employees.list(orgId, { ...one, employment_status: 'on_leave' }),
      ),
      employeesTerminated: total(
        this.employees.list(orgId, { ...one, employment_status: 'terminated' }),
      ),
      workflowsActive: workflowTotal(true),
      workflowsTotal: workflowTotal(),
      events: forkJoin(
        Object.fromEntries(
          EVENT_STATUSES.map((s) => [
            s,
            total(this.events.list(orgId, { ...one, event_status: s })),
          ]),
        ) as Record<IntegrationEventStatus, Observable<Count>>,
      ),
      deadLettersOpen: total(this.deadLetters.list(orgId, { ...one, entry_status: 'open' })),
      conflictsOpen: total(this.conflicts.list(orgId, { ...one, conflict_status: 'open' })),
      conflictsBySeverity: forkJoin({
        low: total(
          this.conflicts.list(orgId, { ...one, conflict_status: 'open', severity: 'low' }),
        ),
        medium: total(
          this.conflicts.list(orgId, { ...one, conflict_status: 'open', severity: 'medium' }),
        ),
        high: total(
          this.conflicts.list(orgId, { ...one, conflict_status: 'open', severity: 'high' }),
        ),
        critical: total(
          this.conflicts.list(orgId, { ...one, conflict_status: 'open', severity: 'critical' }),
        ),
      }),
      connectors: this.connectors.list(orgId).pipe(
        map((page) => page.items),
        catchError((e: unknown) => of(ApiError.from(e))),
      ),
    });
  }

  departmentsList(orgId: string): Observable<Department[]> {
    return this.departments.list(orgId).pipe(map((p) => p.items));
  }

  /** Workflow outcomes and retries per day, from the audit log (needs `audit:read`). */
  dailyActivity(orgId: string, days = 7): Observable<DailyActivity> {
    const windows = dayWindows(days);
    const count = (
      action: string,
      w: { since: string; until: string },
      outcome?: 'success' | 'failure',
    ) =>
      this.audit
        .list(orgId, { action, outcome, since: w.since, until: w.until, limit: 1 })
        .pipe(map((p) => p.total));
    return forkJoin({
      succeeded: forkJoin(windows.map((w) => count('workflow.executed', w, 'success'))),
      failed: forkJoin(windows.map((w) => count('workflow.executed', w, 'failure'))),
      retries: forkJoin(windows.map((w) => count('sync.retry_scheduled', w))),
    }).pipe(map((r) => ({ days: windows.map((w) => w.label), ...r })));
  }
}
