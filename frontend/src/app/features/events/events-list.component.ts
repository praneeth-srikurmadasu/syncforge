import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { EVENT_TYPES, IntegrationEvent, Page } from '../../core/api/models';
import { EventQuery, EventsApi } from '../../core/api/operations.api';
import { EmployeesApi } from '../../core/api/workforce.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { humanize } from '../../core/util/format';
import { useAutoRefresh } from '../../shared/auto-refresh';
import { useQueryState } from '../../shared/query-state';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import {
  EmployeePickerComponent,
  EmployeeRefLike,
} from '../../shared/ui/employee-picker.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { IconComponent } from '../../shared/ui/icon.component';

const PAGE_SIZE = 25;
const STATUSES = ['pending', 'processing', 'retrying', 'completed', 'dead_letter'] as const;

@Component({
  selector: 'sf-events-list',
  imports: [
    PageHeaderComponent,
    StatusBadgeComponent,
    EmployeeNameComponent,
    EmployeePickerComponent,
    PaginationComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
    IconComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-page-header
        title="Events"
        description="Lifecycle events recorded with each employee change, and how far background processing has taken them."
      >
        <label class="sf-checkbox">
          <input
            type="checkbox"
            [checked]="refresh.enabled()"
            (change)="refresh.enabled.set(!refresh.enabled())"
          />
          Refresh every {{ refresh.seconds }} s
        </label>
        <button type="button" class="sf-btn" (click)="events.reload()">
          <sf-icon name="refresh" [size]="14" /> Refresh
        </button>
      </sf-page-header>

      <div class="sf-card">
        <div class="sf-filters">
          <div class="sf-field">
            <label for="ev-status">Status</label>
            <select
              id="ev-status"
              class="sf-select"
              (change)="q.set({ status: $any($event.target).value })"
            >
              <option value="">Any status</option>
              @for (s of statuses; track s) {
                <option [value]="s" [selected]="q.get('status') === s">
                  {{ s === 'dead_letter' ? 'Dead letter' : humanize(s) }}
                </option>
              }
            </select>
          </div>
          <div class="sf-field">
            <label for="ev-type">Event type</label>
            <select
              id="ev-type"
              class="sf-select"
              (change)="q.set({ type: $any($event.target).value })"
            >
              <option value="">Any type</option>
              @for (t of types; track t) {
                <option [value]="t" [selected]="q.get('type') === t">{{ t }}</option>
              }
            </select>
          </div>
          <div class="sf-field employee">
            <label for="ev-employee">Employee</label>
            <sf-employee-picker
              inputId="ev-employee"
              [value]="employeeFilter()"
              (valueChange)="setEmployee($event)"
              [includeTerminated]="true"
              emptyText="No matching employee."
            />
          </div>
          @if (q.get('status') || q.get('type') || q.get('employee')) {
            <button type="button" class="sf-btn sf-btn--ghost" (click)="q.clear()">
              Clear filters
            </button>
          }
        </div>
        <p class="note sf-faint">
          The API filters events by status, type and employee; it has no date filter. Newest first.
        </p>

        @if (events.error(); as err) {
          <sf-error-state [error]="err" (retry)="events.reload()" />
        } @else if (events.hasValue()) {
          @let page = events.value();
          @if (page.items.length === 0) {
            <sf-empty-state
              icon="activity"
              title="No events match"
              message="Events are recorded when employees are created, changed or terminated."
            />
          } @else {
            <div class="sf-table-wrap">
              <table class="sf-table">
                <thead>
                  <tr>
                    <th scope="col">Event</th>
                    <th scope="col">Employee</th>
                    <th scope="col">Status</th>
                    <th scope="col" class="sf-cell-num">Attempts</th>
                    <th scope="col">Changed fields</th>
                    <th scope="col">Recorded</th>
                    <th scope="col">Finished / next try</th>
                  </tr>
                </thead>
                <tbody>
                  @for (e of page.items; track e.id) {
                    <tr class="sf-row-link" (click)="open(e)">
                      <td>
                        <span class="sf-cell-primary">{{ humanize(e.event_type) }}</span>
                        <code class="sf-faint type">{{ e.event_type }}</code>
                      </td>
                      <td><sf-employee-name [id]="e.employee_id" /></td>
                      <td><sf-status [value]="e.status" /></td>
                      <td class="sf-cell-num">{{ e.attempts }}</td>
                      <td class="sf-muted fields">{{ e.changed_fields.join(', ') || '-' }}</td>
                      <td><sf-time [value]="e.created_at" /></td>
                      <td>
                        @if (e.completed_at) {
                          <sf-time [value]="e.completed_at" />
                        } @else if (e.next_attempt_at) {
                          <span class="warn">retry <sf-time [value]="e.next_attempt_at" /></span>
                        } @else {
                          <span class="sf-faint">-</span>
                        }
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
          <sf-skeleton [rows]="8" />
        }
      </div>
    </div>
  `,
  styles: `
    .employee {
      width: 280px !important;
    }
    .note {
      padding: var(--sf-space-2) var(--sf-space-4) 0;
      font-size: var(--sf-text-xs);
    }
    .type {
      display: block;
      font-size: var(--sf-text-xs);
    }
    .fields {
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .warn {
      color: var(--sf-warning);
    }
  `,
})
export class EventsListComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(EventsApi);
  private readonly employeesApi = inject(EmployeesApi);
  private readonly router = inject(Router);
  protected readonly q = useQueryState();

  protected readonly statuses = STATUSES;
  protected readonly types = EVENT_TYPES;
  protected readonly humanize = humanize;

  protected readonly query = computed<EventQuery>(() => {
    this.q.params();
    return {
      event_status: (this.q.get('status') as EventQuery['event_status']) || undefined,
      event_type: this.q.get('type') || undefined,
      employee_id: this.q.get('employee') || undefined,
      limit: PAGE_SIZE,
      offset: this.q.number('offset'),
    };
  });

  protected readonly events = httpResource<Page<IntegrationEvent>>(() =>
    this.api.listRequest(this.org.orgId(), this.query()),
  );
  protected readonly refresh = useAutoRefresh(() => this.events.reload());

  /** The chosen employee, shown by name; loaded once when the page opens with a filter. */
  private readonly chosen = signal<EmployeeRefLike | null>(null);
  protected readonly employeeFilter = computed(() => {
    const id = this.q.get('employee');
    const c = this.chosen();
    return id && c?.id === id ? c : null;
  });

  constructor() {
    const id = this.q.get('employee');
    if (id) {
      this.employeesApi.get(this.org.orgId(), id).subscribe({
        next: (e) => this.chosen.set(e),
        error: () =>
          this.chosen.set({ id, full_name: 'Unknown employee', employee_number: id.slice(0, 8) }),
      });
    }
  }

  protected setEmployee(e: EmployeeRefLike | null): void {
    this.chosen.set(e);
    this.q.set({ employee: e?.id ?? '' });
  }

  protected open(e: IntegrationEvent): void {
    void this.router.navigate(['/o', this.org.orgId(), 'events', e.id]);
  }
}
