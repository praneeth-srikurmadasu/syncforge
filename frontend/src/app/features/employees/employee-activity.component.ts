import { httpResource } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  linkedSignal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuditEntry, Conflict, IntegrationEvent, Page } from '../../core/api/models';
import { AuditApi, ConflictsApi, EventsApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { humanize } from '../../core/util/format';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { JsonViewComponent } from '../../shared/ui/json-view.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

const LIMIT = 10;

/** One employee's lifecycle events, conflicts or audit history (one tab of the detail page). */
@Component({
  selector: 'sf-employee-activity',
  imports: [
    RouterLink,
    StatusBadgeComponent,
    JsonViewComponent,
    PaginationComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @switch (kind()) {
      @case ('events') {
        @if (events.error(); as err) {
          <sf-error-state [error]="err" (retry)="events.reload()" />
        } @else if (events.value(); as page) {
          @if (page.items.length === 0) {
            <sf-empty-state icon="activity" title="No lifecycle events for this employee" />
          } @else {
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">Event</th>
                  <th scope="col">Status</th>
                  <th scope="col">Changed fields</th>
                  <th scope="col" class="sf-cell-num">Attempts</th>
                  <th scope="col">Recorded</th>
                </tr>
              </thead>
              <tbody>
                @for (ev of page.items; track ev.id) {
                  <tr>
                    <td class="sf-cell-primary">{{ humanize(ev.event_type) }}</td>
                    <td><sf-status [value]="ev.status" /></td>
                    <td class="sf-muted">{{ ev.changed_fields.join(', ') || '-' }}</td>
                    <td class="sf-cell-num">{{ ev.attempts }}</td>
                    <td><sf-time [value]="ev.created_at" /></td>
                  </tr>
                }
              </tbody>
            </table>
            <sf-pagination
              [total]="page.total"
              [limit]="page.limit"
              [offset]="page.offset"
              (offsetChange)="offset.set($event)"
            />
          }
        } @else {
          <sf-skeleton [rows]="4" />
        }
      }
      @case ('conflicts') {
        @if (conflicts.error(); as err) {
          <sf-error-state [error]="err" (retry)="conflicts.reload()" />
        } @else if (conflicts.value(); as page) {
          @if (page.items.length === 0) {
            <sf-empty-state
              icon="compare"
              title="No conflicts recorded"
              message="Conflicts appear when reconciliation finds this person's data different in a connected application."
            />
          } @else {
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">SyncForge</th>
                  <th scope="col">Application</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last detected</th>
                </tr>
              </thead>
              <tbody>
                @for (c of page.items; track c.id) {
                  <tr>
                    <td class="sf-cell-primary">
                      <a [routerLink]="['/o', orgId(), 'conflicts', c.id]">{{
                        humanize(c.field)
                      }}</a>
                    </td>
                    <td>{{ c.syncforge_value ?? '-' }}</td>
                    <td>{{ c.external_value ?? '-' }}</td>
                    <td><sf-status [value]="c.severity" /></td>
                    <td><sf-status [value]="c.status" /></td>
                    <td><sf-time [value]="c.last_detected_at" /></td>
                  </tr>
                }
              </tbody>
            </table>
            <sf-pagination
              [total]="page.total"
              [limit]="page.limit"
              [offset]="page.offset"
              (offsetChange)="offset.set($event)"
            />
          }
        } @else {
          <sf-skeleton [rows]="4" />
        }
      }
      @case ('history') {
        @if (history.error(); as err) {
          <sf-error-state [error]="err" (retry)="history.reload()" />
        } @else if (history.value(); as page) {
          @if (page.items.length === 0) {
            <sf-empty-state icon="file-clock" title="No recorded changes" />
          } @else {
            <ol class="timeline">
              @for (a of page.items; track a.id) {
                <li>
                  <div class="row">
                    <code class="action">{{ a.action }}</code>
                    <sf-status [value]="a.outcome" />
                    <span class="sf-muted">{{
                      a.actor_type === 'system' ? 'by the system' : 'by a user'
                    }}</span>
                    <span class="sf-spacer"></span>
                    <sf-time [value]="a.created_at" />
                  </div>
                  @if (hasDetails(a)) {
                    <details>
                      <summary>Details</summary>
                      <sf-json [value]="a.details" />
                    </details>
                  }
                </li>
              }
            </ol>
            <sf-pagination
              [total]="page.total"
              [limit]="page.limit"
              [offset]="page.offset"
              (offsetChange)="offset.set($event)"
            />
          }
        } @else {
          <sf-skeleton [rows]="4" />
        }
      }
    }
  `,
  styles: `
    .timeline {
      margin: 0;
      padding: 0 var(--sf-space-4);
      list-style: none;
    }
    .timeline li {
      padding: var(--sf-space-3) 0;
      border-bottom: 1px solid var(--sf-border);
    }
    .timeline li:last-child {
      border-bottom: none;
    }
    .row {
      display: flex;
      align-items: center;
      gap: var(--sf-space-3);
      flex-wrap: wrap;
      font-size: var(--sf-text-sm);
    }
    .action {
      font-weight: 500;
    }
    details {
      margin-top: var(--sf-space-2);
      font-size: var(--sf-text-sm);
    }
    summary {
      cursor: pointer;
      color: var(--sf-text-muted);
      margin-bottom: var(--sf-space-2);
    }
  `,
})
export class EmployeeActivityComponent {
  readonly employeeId = input.required<string>();
  readonly kind = input.required<'events' | 'conflicts' | 'history'>();

  private readonly org = inject(OrgContextService);
  protected readonly orgId = this.org.orgId;
  private readonly eventsApi = inject(EventsApi);
  private readonly conflictsApi = inject(ConflictsApi);
  private readonly auditApi = inject(AuditApi);

  /** Back to the first page whenever another tab is shown. */
  protected readonly offset = linkedSignal(() => {
    this.kind();
    return 0;
  });
  protected readonly humanize = humanize;

  private readonly page = computed(() => ({ limit: LIMIT, offset: this.offset() }));

  // Each resource only requests when its tab is shown (undefined = idle).
  protected readonly events = httpResource<Page<IntegrationEvent>>(() =>
    this.kind() === 'events'
      ? this.eventsApi.listRequest(this.org.orgId(), {
          employee_id: this.employeeId(),
          ...this.page(),
        })
      : undefined,
  );
  protected readonly conflicts = httpResource<Page<Conflict>>(() =>
    this.kind() === 'conflicts'
      ? this.conflictsApi.listRequest(this.org.orgId(), {
          employee_id: this.employeeId(),
          ...this.page(),
        })
      : undefined,
  );
  protected readonly history = httpResource<Page<AuditEntry>>(() =>
    this.kind() === 'history'
      ? this.auditApi.listRequest(this.org.orgId(), {
          resource_type: 'employee',
          resource_id: this.employeeId(),
          ...this.page(),
        })
      : undefined,
  );

  protected hasDetails(a: AuditEntry): boolean {
    return Object.keys(a.details ?? {}).length > 0;
  }
}
