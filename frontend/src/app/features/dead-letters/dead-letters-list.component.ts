import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { Connector, DeadLetter, Page } from '../../core/api/models';
import { DeadLetterQuery, DeadLettersApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { humanize } from '../../core/util/format';
import { useQueryState } from '../../shared/query-state';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

@Component({
  selector: 'sf-dead-letters-list',
  imports: [
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    EmployeeNameComponent,
    PaginationComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-page-header
        title="Dead-letter queue"
        [crumbs]="[
          { label: 'Reliability', link: ['/o', org.orgId(), 'reliability'] },
          { label: 'Dead-letter queue' },
        ]"
        description="Events whose processing stopped after the retry budget ran out, or on an error that retrying cannot fix. Each can be inspected and replayed."
      />
      <div class="sf-card">
        <div class="sf-filters">
          <div class="sf-field">
            <label for="dl-status">Status</label>
            <select
              id="dl-status"
              class="sf-select"
              (change)="q.set({ status: $any($event.target).value })"
            >
              <option value="open" [selected]="status() === 'open'">Open</option>
              <option value="replayed" [selected]="status() === 'replayed'">Replayed</option>
              <option value="all" [selected]="status() === 'all'">All</option>
            </select>
          </div>
          <div class="sf-field">
            <label for="dl-connector">Connector</label>
            <select
              id="dl-connector"
              class="sf-select"
              (change)="q.set({ connector: $any($event.target).value })"
            >
              <option value="">Any connector</option>
              @for (c of connectors.value()?.items ?? []; track c.id) {
                <option [value]="c.id" [selected]="q.get('connector') === c.id">
                  {{ c.name }}
                </option>
              }
            </select>
          </div>
        </div>

        @if (entries.error(); as err) {
          <sf-error-state [error]="err" (retry)="entries.reload()" />
        } @else if (entries.hasValue()) {
          @let page = entries.value();
          @if (page.items.length === 0) {
            <sf-empty-state
              icon="inbox"
              [title]="status() === 'open' ? 'Nothing waiting for replay' : 'No entries'"
              message="Events land here only when a step fails after its retries, or with an error that retrying cannot fix."
            />
          } @else {
            <div class="sf-table-wrap">
              <table class="sf-table">
                <thead>
                  <tr>
                    <th scope="col">Employee</th>
                    <th scope="col">Event</th>
                    <th scope="col">Failed step</th>
                    <th scope="col">Reason</th>
                    <th scope="col">Error</th>
                    <th scope="col" class="sf-cell-num">Attempts</th>
                    <th scope="col">Status</th>
                    <th scope="col">When</th>
                  </tr>
                </thead>
                <tbody>
                  @for (d of page.items; track d.id) {
                    <tr class="sf-row-link" (click)="open(d)">
                      <td><sf-employee-name [id]="d.employee_id" /></td>
                      <td>
                        <a
                          [routerLink]="['/o', org.orgId(), 'dead-letters', d.id]"
                          (click)="$event.stopPropagation()"
                          >{{ humanize(d.event_type) }}</a
                        >
                      </td>
                      <td>
                        @if (d.connector_id) {
                          {{ connectorNames().get(d.connector_id) ?? 'connector' }}
                        }
                        <code class="sf-faint">{{ d.operation ?? '' }}</code>
                      </td>
                      <td>
                        <sf-badge [tone]="d.reason === 'non_retryable' ? 'danger' : 'warning'">{{
                          humanize(d.reason)
                        }}</sf-badge>
                      </td>
                      <td>
                        {{ humanize(d.error_category) }}
                        @if (d.http_status) {
                          <code class="sf-faint">HTTP {{ d.http_status }}</code>
                        }
                      </td>
                      <td class="sf-cell-num">{{ d.attempts }}</td>
                      <td><sf-status [value]="d.status" /></td>
                      <td>
                        <sf-time
                          [value]="d.status === 'replayed' ? d.replayed_at : d.dead_lettered_at"
                        />
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
            <sf-pagination
              [total]="page.total"
              [limit]="page.limit"
              [offset]="page.offset"
              (offsetChange)="q.set({ offset: $event || null }, false)"
            />
          }
        } @else {
          <sf-skeleton [rows]="6" />
        }
      </div>
    </div>
  `,
})
export class DeadLettersListComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(DeadLettersApi);
  private readonly connectorsApi = inject(ConnectorsApi);
  private readonly router = inject(Router);
  protected readonly q = useQueryState();
  protected readonly humanize = humanize;

  /** Open entries by default: that is the work to do. */
  protected readonly status = computed(() => this.q.get('status') || 'open');
  private readonly query = computed<DeadLetterQuery>(() => ({
    entry_status:
      this.status() === 'all' ? undefined : (this.status() as DeadLetterQuery['entry_status']),
    connector_id: this.q.get('connector') || undefined,
    limit: 25,
    offset: this.q.number('offset'),
  }));
  protected readonly entries = httpResource<Page<DeadLetter>>(() =>
    this.api.listRequest(this.org.orgId(), this.query()),
  );
  protected readonly connectors = httpResource<Page<Connector>>(() =>
    this.connectorsApi.listRequest(this.org.orgId()),
  );
  protected readonly connectorNames = computed(
    () => new Map((this.connectors.value()?.items ?? []).map((c) => [c.id, c.name])),
  );

  protected open(d: DeadLetter): void {
    void this.router.navigate(['/o', this.org.orgId(), 'dead-letters', d.id]);
  }
}
