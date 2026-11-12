import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { Attempt, Connector, IntegrationEventDetail, Page } from '../../core/api/models';
import { EventsApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { formatDuration, humanize } from '../../core/util/format';
import { useAutoRefresh } from '../../shared/auto-refresh';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { CopyIdComponent } from '../../shared/ui/copy-id.component';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

const FINAL = new Set(['completed', 'dead_letter']);

@Component({
  selector: 'sf-event-detail',
  imports: [
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    CopyIdComponent,
    EmployeeNameComponent,
    IconComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './event-detail.component.html',
  styleUrl: './event-detail.component.scss',
})
export class EventDetailComponent {
  readonly id = input.required<string>();

  protected readonly org = inject(OrgContextService);
  private readonly api = inject(EventsApi);
  private readonly connectorsApi = inject(ConnectorsApi);
  protected readonly humanize = humanize;
  protected readonly formatDuration = formatDuration;

  protected readonly event = httpResource<IntegrationEventDetail>(() =>
    this.api.getRequest(this.org.orgId(), this.id()),
  );
  protected readonly attempts = httpResource<Attempt[]>(() =>
    this.api.attemptsRequest(this.org.orgId(), this.id()),
  );
  private readonly connectors = httpResource<Page<Connector>>(() =>
    this.connectorsApi.listRequest(this.org.orgId()),
  );
  protected readonly connectorNames = computed(
    () => new Map((this.connectors.value()?.items ?? []).map((c) => [c.id, c.name])),
  );

  protected readonly refresh = useAutoRefresh(() => this.reload(), 3);
  protected readonly isFinal = computed(() => FINAL.has(this.event.value()?.status ?? ''));

  constructor() {
    // Follow an event that is still being processed; stop once it settles.
    effect(() => {
      const status = this.event.value()?.status;
      if (status) this.refresh.enabled.set(!FINAL.has(status));
    });
  }

  protected reload(): void {
    this.event.reload();
    this.attempts.reload();
  }

  protected connectorName(id: string): string {
    return this.connectorNames().get(id) ?? id.slice(0, 8);
  }
}
