import { Injectable, inject } from '@angular/core';
import { Observable, catchError, forkJoin, map, of } from 'rxjs';
import { ApiError } from '../../core/api/api-error';
import { ConnectorsApi } from '../../core/api/integrations.api';
import {
  Connector,
  Department,
  IntegrationEventStatus,
  OrganizationSummary,
  ProcessingStats,
} from '../../core/api/models';
import { AuditApi } from '../../core/api/operations.api';
import { OrganizationsApi } from '../../core/api/organizations.api';
import { DepartmentsApi } from '../../core/api/workforce.api';

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
  processing: ProcessingStats | ApiError;
}

/** Maps the summary onto the dashboard's figures; a failed summary fails each figure. */
export function toOverview(
  summary: OrganizationSummary | ApiError,
  connectors: Connector[] | ApiError,
): Overview {
  if (summary instanceof ApiError) {
    const e = summary;
    return {
      employeesActive: e,
      employeesOnLeave: e,
      employeesTerminated: e,
      workflowsActive: e,
      workflowsTotal: e,
      events: Object.fromEntries(EVENT_STATUSES.map((s) => [s, e])) as Record<
        IntegrationEventStatus,
        Count
      >,
      deadLettersOpen: e,
      conflictsOpen: e,
      conflictsBySeverity: { low: e, medium: e, high: e, critical: e },
      connectors,
      processing: e,
    };
  }
  const c = summary.conflicts_open;
  return {
    employeesActive: summary.employees['active'] ?? 0,
    employeesOnLeave: summary.employees['on_leave'] ?? 0,
    employeesTerminated: summary.employees['terminated'] ?? 0,
    workflowsActive: summary.workflows['active'] ?? 0,
    workflowsTotal: summary.workflows['total'] ?? 0,
    events: Object.fromEntries(EVENT_STATUSES.map((s) => [s, summary.events[s] ?? 0])) as Record<
      IntegrationEventStatus,
      Count
    >,
    deadLettersOpen: summary.dead_letters_open,
    conflictsOpen: c['total'] ?? 0,
    conflictsBySeverity: {
      low: c['low'] ?? 0,
      medium: c['medium'] ?? 0,
      high: c['high'] ?? 0,
      critical: c['critical'] ?? 0,
    },
    connectors,
    processing: summary.processing,
  };
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
 * The dashboard's figures come from GET .../summary (one request; each count equals the
 * `total` of the matching list endpoint), the connector health table from the connector
 * list, and daily activity from audit-log entries in each day's window. Nothing here is
 * estimated. If the summary fails, every figure from it shows that error.
 */
@Injectable({ providedIn: 'root' })
export class DashboardData {
  private readonly departments = inject(DepartmentsApi);
  private readonly organizations = inject(OrganizationsApi);
  private readonly connectors = inject(ConnectorsApi);
  private readonly audit = inject(AuditApi);

  overview(orgId: string): Observable<Overview> {
    return forkJoin({
      summary: this.organizations
        .summary(orgId)
        .pipe(catchError((e: unknown) => of(ApiError.from(e)))),
      connectors: this.connectors.list(orgId).pipe(
        map((page) => page.items),
        catchError((e: unknown) => of(ApiError.from(e))),
      ),
    }).pipe(map(({ summary, connectors }) => toOverview(summary, connectors)));
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
