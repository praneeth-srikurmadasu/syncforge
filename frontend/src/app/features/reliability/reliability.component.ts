import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, forkJoin, map, of } from 'rxjs';
import { ApiError } from '../../core/api/api-error';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { AuditEntry, Connector, Page } from '../../core/api/models';
import { AuditApi, DeadLettersApi, EventsApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { humanize } from '../../core/util/format';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { MetricCardComponent } from '../../shared/ui/metric-card.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

type Count = number | ApiError;
const HOUR = 3600_000;

/** Retries, dead letters, circuit breakers and rate limits in one place. */
@Component({
  selector: 'sf-reliability',
  imports: [
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    MetricCardComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './reliability.component.html',
  styleUrl: './reliability.component.scss',
})
export class ReliabilityComponent {
  protected readonly org = inject(OrgContextService);
  private readonly events = inject(EventsApi);
  private readonly deadLetters = inject(DeadLettersApi);
  private readonly audit = inject(AuditApi);
  private readonly connectorsApi = inject(ConnectorsApi);
  protected readonly humanize = humanize;

  protected readonly canAudit = computed(() => {
    this.org.organization();
    return this.org.can('audit:read');
  });

  protected readonly connectors = httpResource<Page<Connector>>(() =>
    this.connectorsApi.listRequest(this.org.orgId()),
  );
  protected readonly connectorNames = computed(
    () => new Map((this.connectors.value()?.items ?? []).map((c) => [c.id, c.name])),
  );

  /** Current totals (limit=1 reads `total`); each figure fails independently. */
  protected readonly totals = rxResource({
    params: () => this.org.orgId(),
    stream: ({ params: orgId }) => {
      const total = (source: ReturnType<typeof this.events.list>) =>
        source.pipe(
          map((p) => p.total as Count),
          catchError((e: unknown) => of(ApiError.from(e))),
        );
      return forkJoin({
        retrying: total(this.events.list(orgId, { event_status: 'retrying', limit: 1 })),
        deadLetters: this.deadLetters.list(orgId, { entry_status: 'open', limit: 1 }).pipe(
          map((p) => p.total as Count),
          catchError((e: unknown) => of(ApiError.from(e))),
        ),
      });
    },
  });

  /** Counts over time windows, from the audit log (needs audit:read). */
  protected readonly history = rxResource({
    params: () => (this.canAudit() ? this.org.orgId() : undefined),
    stream: ({ params: orgId }) => {
      const now = Date.now();
      const since = (hours: number) => new Date(now - hours * HOUR).toISOString();
      const count = (action: string, hours: number) =>
        this.audit.list(orgId, { action, since: since(hours), limit: 1 }).pipe(map((p) => p.total));
      return forkJoin({
        retries24h: count('sync.retry_scheduled', 24),
        deadLettered7d: count('event.dead_lettered', 24 * 7),
        circuitOpened7d: count('connector.circuit_opened', 24 * 7),
        replays7d: count('dead_letter.replayed', 24 * 7),
      });
    },
  });

  protected readonly recentRetries = httpResource<Page<AuditEntry>>(() =>
    this.canAudit()
      ? this.audit.listRequest(this.org.orgId(), { action: 'sync.retry_scheduled', limit: 10 })
      : undefined,
  );

  protected readonly circuitsNotClosed = computed(() => {
    const list = this.connectors.value()?.items;
    return list ? list.filter((c) => c.circuit.state !== 'closed').length : null;
  });

  protected value(c: Count | undefined): number | null {
    return typeof c === 'number' ? c : null;
  }

  protected failed(c: Count | undefined): boolean {
    return c instanceof ApiError;
  }

  protected rateLimit(c: Connector): string {
    const limit = (c.config as Record<string, unknown>)['rate_limit_per_minute'];
    return typeof limit === 'number' ? `${limit} per minute` : 'No limit set';
  }

  protected detail(entry: AuditEntry, key: string): string {
    const value = (entry.details as Record<string, unknown>)[key];
    return value === null || value === undefined ? '' : String(value);
  }
}
