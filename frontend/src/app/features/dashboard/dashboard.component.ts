import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { AuditApi, EventsApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { humanize } from '../../core/util/format';
import { BarChartComponent, ChartSeries } from '../../shared/charts/chart.component';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { MetricCardComponent } from '../../shared/ui/metric-card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { ConnectorHealthComponent } from './connector-health.component';
import { Count, DashboardData, EVENT_STATUSES } from './dashboard-data';

@Component({
  selector: 'sf-dashboard',
  imports: [
    RouterLink,
    PageHeaderComponent,
    MetricCardComponent,
    BarChartComponent,
    StatusBadgeComponent,
    EmployeeNameComponent,
    IconComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
    ConnectorHealthComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent {
  protected readonly org = inject(OrgContextService);
  private readonly data = inject(DashboardData);
  private readonly eventsApi = inject(EventsApi);
  private readonly auditApi = inject(AuditApi);

  protected readonly canAudit = computed(() => {
    this.org.organization();
    return this.org.can('audit:read');
  });

  protected readonly overview = rxResource({
    params: () => this.org.orgId(),
    stream: ({ params }) => this.data.overview(params),
  });

  protected readonly activity = rxResource({
    params: () => (this.canAudit() ? this.org.orgId() : undefined),
    stream: ({ params }) => this.data.dailyActivity(params),
  });

  protected readonly recentEvents = rxResource({
    params: () => this.org.orgId(),
    stream: ({ params }) => this.eventsApi.list(params, { limit: 8 }),
  });

  protected readonly recentAudit = rxResource({
    params: () => (this.canAudit() ? this.org.orgId() : undefined),
    stream: ({ params }) => this.auditApi.list(params, { limit: 8 }),
  });

  protected readonly departments = rxResource({
    params: () => this.org.orgId(),
    stream: ({ params }) => this.data.departmentsList(params),
  });

  // ---- derived figures (only from loaded data) ----

  protected value(count: Count | undefined): number | null {
    return typeof count === 'number' ? count : null;
  }

  protected failed(count: Count | undefined): boolean {
    return count instanceof ApiError;
  }

  protected readonly connectors = computed(() => {
    const c = this.overview.value()?.connectors;
    return Array.isArray(c) ? c : null;
  });

  protected readonly connectorsError = computed(() => {
    const c = this.overview.value()?.connectors;
    return c instanceof ApiError ? c : null;
  });

  protected readonly connectedCount = computed(() => {
    const list = this.connectors();
    return list ? list.filter((c) => c.status === 'connected').length : null;
  });

  protected readonly inFlight = computed<Count | undefined>(() => {
    const e = this.overview.value()?.events;
    if (!e) return undefined;
    const parts = [e.pending, e.processing, e.retrying];
    const err = parts.find((p) => p instanceof ApiError);
    return err ?? parts.reduce<number>((sum, p) => sum + (p as number), 0);
  });

  protected readonly eventChart = computed(() => {
    const e = this.overview.value()?.events;
    if (!e || EVENT_STATUSES.some((s) => e[s] instanceof ApiError)) return null;
    return {
      categories: EVENT_STATUSES.map((s) => (s === 'dead_letter' ? 'Dead letter' : humanize(s))),
      series: [
        { name: 'Events', values: EVENT_STATUSES.map((s) => e[s] as number), tone: 'accent' },
      ] as ChartSeries[],
      total: EVENT_STATUSES.reduce((sum, s) => sum + (e[s] as number), 0),
    };
  });

  protected readonly activityChart = computed(() => {
    const a = this.activity.value();
    if (!a) return null;
    const succeeded = a.succeeded.reduce((x, y) => x + y, 0);
    const failed = a.failed.reduce((x, y) => x + y, 0);
    const retries = a.retries.reduce((x, y) => x + y, 0);
    return {
      days: a.days,
      outcomes: [
        { name: 'Succeeded', values: a.succeeded, tone: 'success' },
        { name: 'Failed', values: a.failed, tone: 'danger' },
      ] as ChartSeries[],
      retries: [{ name: 'Retries scheduled', values: a.retries, tone: 'warning' }] as ChartSeries[],
      succeeded,
      failed,
      retryTotal: retries,
      rate:
        succeeded + failed > 0 ? Math.round((succeeded / (succeeded + failed)) * 1000) / 10 : null,
    };
  });

  protected readonly severityChart = computed(() => {
    const s = this.overview.value()?.conflictsBySeverity;
    if (!s) return null;
    const keys = ['critical', 'high', 'medium', 'low'] as const;
    if (keys.some((k) => s[k] instanceof ApiError)) return null;
    return keys.map((k) => ({ key: k, count: s[k] as number }));
  });

  protected readonly departmentChart = computed(() => {
    const list = this.departments.value();
    if (!list) return null;
    const sorted = [...list].sort((a, b) => b.employee_count - a.employee_count).slice(0, 8);
    return {
      categories: sorted.map((d) => d.name),
      series: [
        { name: 'Employees', values: sorted.map((d) => d.employee_count), tone: 'accent' },
      ] as ChartSeries[],
      hidden: Math.max(0, list.length - sorted.length),
    };
  });

  protected readonly humanize = humanize;
  protected readonly Math = Math;

  protected refresh(): void {
    this.overview.reload();
    this.activity.reload();
    this.recentEvents.reload();
    this.recentAudit.reload();
    this.departments.reload();
  }
}
