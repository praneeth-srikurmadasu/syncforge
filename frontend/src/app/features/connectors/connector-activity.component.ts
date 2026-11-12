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
import { ConnectorsApi } from '../../core/api/integrations.api';
import { AuditEntry, Conflict, DeadLetter, ExternalAccount, Page } from '../../core/api/models';
import { AuditApi, ConflictsApi, DeadLettersApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { humanize } from '../../core/util/format';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import { JsonViewComponent } from '../../shared/ui/json-view.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

const LIMIT = 10;
type Kind = 'accounts' | 'dead-letters' | 'conflicts' | 'history';

/** One tab of the connector page: linked accounts, dead letters, conflicts or history. */
@Component({
  selector: 'sf-connector-activity',
  imports: [
    RouterLink,
    StatusBadgeComponent,
    EmployeeNameComponent,
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
      @case ('accounts') {
        @if (accounts.error(); as err) {
          <sf-error-state [error]="err" (retry)="accounts.reload()" />
        } @else if (accounts.value(); as page) {
          @if (page.items.length === 0) {
            <sf-empty-state
              icon="users"
              title="No linked accounts yet"
              message="Accounts appear when a workflow or a manual operation creates a user in this application."
            />
          } @else {
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">Employee</th>
                  <th scope="col">Account ID in the application</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last synchronized</th>
                  <th scope="col">Linked</th>
                </tr>
              </thead>
              <tbody>
                @for (a of page.items; track a.id) {
                  <tr>
                    <td><sf-employee-name [id]="a.employee_id" /></td>
                    <td>
                      <code>{{ a.external_id }}</code>
                    </td>
                    <td><sf-status [value]="a.status" /></td>
                    <td><sf-time [value]="a.last_synced_at" /></td>
                    <td><sf-time [value]="a.created_at" /></td>
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
      @case ('dead-letters') {
        @if (deadLetters.error(); as err) {
          <sf-error-state [error]="err" (retry)="deadLetters.reload()" />
        } @else if (deadLetters.value(); as page) {
          @if (page.items.length === 0) {
            <sf-empty-state icon="inbox" title="No dead letters for this connector" />
          } @else {
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">Employee</th>
                  <th scope="col">Event</th>
                  <th scope="col">Operation</th>
                  <th scope="col">Error</th>
                  <th scope="col">Status</th>
                  <th scope="col">Dead-lettered</th>
                </tr>
              </thead>
              <tbody>
                @for (d of page.items; track d.id) {
                  <tr>
                    <td><sf-employee-name [id]="d.employee_id" /></td>
                    <td>
                      <a [routerLink]="['/o', orgId(), 'dead-letters', d.id]">{{
                        humanize(d.event_type)
                      }}</a>
                    </td>
                    <td>
                      <code>{{ d.operation ?? '-' }}</code>
                    </td>
                    <td>
                      {{ humanize(d.error_category) }}
                      @if (d.http_status) {
                        <code class="sf-faint">HTTP {{ d.http_status }}</code>
                      }
                    </td>
                    <td><sf-status [value]="d.status" /></td>
                    <td><sf-time [value]="d.dead_lettered_at" /></td>
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
              title="No conflicts with this application"
              message="Reconcile compares SyncForge's records with the accounts in this application."
            />
          } @else {
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">Employee</th>
                  <th scope="col">Field</th>
                  <th scope="col">SyncForge</th>
                  <th scope="col">Application</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                @for (c of page.items; track c.id) {
                  <tr>
                    <td><sf-employee-name [id]="c.employee_id" /></td>
                    <td>{{ humanize(c.field) }}</td>
                    <td>{{ c.syncforge_value ?? '-' }}</td>
                    <td>{{ c.external_value ?? '-' }}</td>
                    <td><sf-status [value]="c.severity" /></td>
                    <td><sf-status [value]="c.status" /></td>
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
export class ConnectorActivityComponent {
  readonly connectorId = input.required<string>();
  readonly kind = input.required<Kind>();

  private readonly org = inject(OrgContextService);
  protected readonly orgId = this.org.orgId;
  private readonly connectorsApi = inject(ConnectorsApi);
  private readonly deadLettersApi = inject(DeadLettersApi);
  private readonly conflictsApi = inject(ConflictsApi);
  private readonly auditApi = inject(AuditApi);
  protected readonly humanize = humanize;

  protected readonly offset = linkedSignal(() => {
    this.kind();
    return 0;
  });
  private readonly page = computed(() => ({ limit: LIMIT, offset: this.offset() }));

  protected readonly accounts = httpResource<Page<ExternalAccount>>(() =>
    this.kind() === 'accounts'
      ? this.connectorsApi.accountsRequest(this.org.orgId(), this.connectorId(), this.page())
      : undefined,
  );
  protected readonly deadLetters = httpResource<Page<DeadLetter>>(() =>
    this.kind() === 'dead-letters'
      ? this.deadLettersApi.listRequest(this.org.orgId(), {
          connector_id: this.connectorId(),
          ...this.page(),
        })
      : undefined,
  );
  protected readonly conflicts = httpResource<Page<Conflict>>(() =>
    this.kind() === 'conflicts'
      ? this.conflictsApi.listRequest(this.org.orgId(), {
          connector_id: this.connectorId(),
          ...this.page(),
        })
      : undefined,
  );
  protected readonly history = httpResource<Page<AuditEntry>>(() =>
    this.kind() === 'history'
      ? this.auditApi.listRequest(this.org.orgId(), {
          resource_type: 'connector',
          resource_id: this.connectorId(),
          ...this.page(),
        })
      : undefined,
  );

  protected hasDetails(a: AuditEntry): boolean {
    return Object.keys(a.details ?? {}).length > 0;
  }
}
