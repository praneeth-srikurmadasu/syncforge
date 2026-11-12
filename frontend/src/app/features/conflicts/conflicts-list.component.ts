import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { Conflict, Connector, Page } from '../../core/api/models';
import { ConflictQuery, ConflictsApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { useQueryState } from '../../shared/query-state';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { CONFLICT_FIELDS, fieldLabel } from './conflict-fields';

@Component({
  selector: 'sf-conflicts-list',
  imports: [
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    EmployeeNameComponent,
    IconComponent,
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
        title="Data conflicts"
        description="Places where an application's copy of an employee differs from SyncForge's. Reconciliation finds them; nothing is overwritten until someone decides, or a policy in automatic mode does."
      >
        <a class="sf-btn" [routerLink]="['/o', org.orgId(), 'policies']">
          <sf-icon name="shield" [size]="14" /> Source-of-truth policies
        </a>
      </sf-page-header>

      <div class="sf-card">
        <div class="sf-filters">
          <div class="sf-field">
            <label for="cf-status">Status</label>
            <select
              id="cf-status"
              class="sf-select"
              (change)="q.set({ status: $any($event.target).value })"
            >
              <option value="open" [selected]="status() === 'open'">Open</option>
              <option value="resolved" [selected]="status() === 'resolved'">Resolved</option>
              <option value="dismissed" [selected]="status() === 'dismissed'">Dismissed</option>
              <option value="all" [selected]="status() === 'all'">All</option>
            </select>
          </div>
          <div class="sf-field">
            <label for="cf-severity">Severity</label>
            <select
              id="cf-severity"
              class="sf-select"
              (change)="q.set({ severity: $any($event.target).value })"
            >
              <option value="">Any severity</option>
              @for (s of severities; track s) {
                <option [value]="s" [selected]="q.get('severity') === s">{{ s }}</option>
              }
            </select>
          </div>
          <div class="sf-field">
            <label for="cf-field">Field</label>
            <select
              id="cf-field"
              class="sf-select"
              (change)="q.set({ field: $any($event.target).value })"
            >
              <option value="">Any field</option>
              @for (f of fields; track f.value) {
                <option [value]="f.value" [selected]="q.get('field') === f.value">
                  {{ f.label }}
                </option>
              }
            </select>
          </div>
          <div class="sf-field">
            <label for="cf-connector">Application</label>
            <select
              id="cf-connector"
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

        @if (conflicts.error(); as err) {
          <sf-error-state [error]="err" (retry)="conflicts.reload()" />
        } @else if (conflicts.hasValue()) {
          @let page = conflicts.value();
          @if (page.items.length === 0) {
            <sf-empty-state
              icon="compare"
              [title]="status() === 'open' ? 'No open conflicts' : 'No conflicts match'"
              message="Run Reconcile on a connector's page to compare its accounts with SyncForge."
            />
          } @else {
            <div class="sf-table-wrap">
              <table class="sf-table">
                <thead>
                  <tr>
                    <th scope="col">Employee</th>
                    <th scope="col">Field</th>
                    <th scope="col">SyncForge</th>
                    <th scope="col">Application</th>
                    <th scope="col">Authoritative</th>
                    <th scope="col">Severity</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last detected</th>
                  </tr>
                </thead>
                <tbody>
                  @for (c of page.items; track c.id) {
                    <tr class="sf-row-link" (click)="open(c)">
                      <td><sf-employee-name [id]="c.employee_id" /></td>
                      <td>
                        <a
                          [routerLink]="['/o', org.orgId(), 'conflicts', c.id]"
                          (click)="$event.stopPropagation()"
                          >{{ fieldLabel(c.field) }}</a
                        >
                      </td>
                      <td class="value">{{ c.syncforge_value ?? '(empty)' }}</td>
                      <td class="value">
                        {{ c.external_value ?? '(empty)' }}
                        <span class="sf-faint src"
                          >in {{ connectorNames().get(c.connector_id) ?? 'connector' }}</span
                        >
                      </td>
                      <td>
                        <sf-badge tone="accent">{{
                          c.authoritative_source === 'syncforge'
                            ? 'SyncForge'
                            : (connectorNames().get(c.connector_id) ?? 'Application')
                        }}</sf-badge>
                      </td>
                      <td><sf-status [value]="c.severity" /></td>
                      <td><sf-status [value]="c.status" /></td>
                      <td>
                        <sf-time [value]="c.last_detected_at" />
                        @if (c.times_detected > 1) {
                          <span class="sf-faint src">{{ c.times_detected }} times</span>
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
          <sf-skeleton [rows]="6" />
        }
      </div>
    </div>
  `,
  styles: `
    .value {
      max-width: 220px;
      overflow-wrap: anywhere;
    }
    .src {
      display: block;
      font-size: var(--sf-text-xs);
    }
  `,
})
export class ConflictsListComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(ConflictsApi);
  private readonly connectorsApi = inject(ConnectorsApi);
  private readonly router = inject(Router);
  protected readonly q = useQueryState();
  protected readonly fields = CONFLICT_FIELDS;
  protected readonly severities = ['critical', 'high', 'medium', 'low'];
  protected readonly fieldLabel = fieldLabel;

  protected readonly status = computed(() => this.q.get('status') || 'open');
  private readonly query = computed<ConflictQuery>(() => ({
    conflict_status:
      this.status() === 'all' ? undefined : (this.status() as ConflictQuery['conflict_status']),
    severity: (this.q.get('severity') as ConflictQuery['severity']) || undefined,
    field: (this.q.get('field') as ConflictQuery['field']) || undefined,
    connector_id: this.q.get('connector') || undefined,
    limit: 25,
    offset: this.q.number('offset'),
  }));
  protected readonly conflicts = httpResource<Page<Conflict>>(() =>
    this.api.listRequest(this.org.orgId(), this.query()),
  );
  protected readonly connectors = httpResource<Page<Connector>>(() =>
    this.connectorsApi.listRequest(this.org.orgId()),
  );
  protected readonly connectorNames = computed(
    () => new Map((this.connectors.value()?.items ?? []).map((c) => [c.id, c.name])),
  );

  protected open(c: Conflict): void {
    void this.router.navigate(['/o', this.org.orgId(), 'conflicts', c.id]);
  }
}
