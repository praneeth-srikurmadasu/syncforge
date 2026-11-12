import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiError } from '../../core/api/api-error';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { Connector, OperationRequest, OperationResponse } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { formatDuration } from '../../core/util/format';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { DialogService } from '../../shared/ui/dialog';
import {
  EmployeePickerComponent,
  EmployeeRefLike,
} from '../../shared/ui/employee-picker.component';
import { JsonViewComponent } from '../../shared/ui/json-view.component';

const OPERATIONS: { value: OperationRequest['operation']; label: string; changes: boolean }[] = [
  { value: 'get_user', label: 'Read the account (get_user)', changes: false },
  { value: 'create_user', label: 'Create the account (create_user)', changes: true },
  { value: 'update_user', label: 'Update the account (update_user)', changes: true },
  { value: 'deactivate_user', label: 'Deactivate the account (deactivate_user)', changes: true },
];

/** POST .../connectors/{id}/operations: one operation for one employee, run now. */
@Component({
  selector: 'sf-connector-operation',
  imports: [FormsModule, EmployeePickerComponent, StatusBadgeComponent, JsonViewComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wrap">
      <p class="sf-muted intro">
        Runs one operation against {{ connector().name }} immediately, outside any workflow - for
        example to provision someone a workflow missed. It is recorded in the audit log.
      </p>
      <div class="sf-form-grid">
        <div class="sf-field">
          <label for="op-employee">Employee</label>
          <sf-employee-picker
            inputId="op-employee"
            [(value)]="employee"
            [includeTerminated]="true"
            emptyText="No matching employee."
          />
        </div>
        <div class="sf-field">
          <label for="op-operation">Operation</label>
          <select id="op-operation" class="sf-select" [(ngModel)]="operation">
            @for (o of operations; track o.value) {
              <option [value]="o.value">{{ o.label }}</option>
            }
          </select>
        </div>
      </div>
      <div class="actions">
        <button
          type="button"
          class="sf-btn sf-btn--primary"
          [disabled]="!employee() || busy() || !connector().credentials"
          (click)="run()"
        >
          {{ busy() ? 'Running…' : 'Run operation' }}
        </button>
        @if (!connector().credentials) {
          <span class="sf-faint">Needs stored credentials.</span>
        }
      </div>

      @if (error(); as err) {
        <div class="sf-alert sf-alert--danger" role="alert">
          <div class="result">
            <strong>{{ err.message }}</strong>
            @if (err.details) {
              <sf-json [value]="err.details" />
            }
            @if (err.requestId) {
              <code class="sf-faint">Request {{ err.requestId }}</code>
            }
          </div>
        </div>
      }
      @if (result(); as r) {
        <div class="sf-alert sf-alert--info" role="status">
          <div class="result">
            <strong>{{ r.operation }} succeeded</strong>
            <dl class="sf-dl">
              <dt>Account ID</dt>
              <dd>
                <code>{{ r.external_id }}</code>
              </dd>
              <dt>Active in the application</dt>
              <dd>{{ r.external_active ? 'Yes' : 'No' }}</dd>
              <dt>Link status in SyncForge</dt>
              <dd><sf-status [value]="r.account_status" /></dd>
              <dt>Response time</dt>
              <dd>{{ formatDuration(r.latency_ms) }}</dd>
            </dl>
          </div>
        </div>
      }
    </div>
  `,
  styles: `
    .wrap {
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-4);
      padding: var(--sf-space-4);
      max-width: 820px;
    }
    .intro {
      font-size: var(--sf-text-sm);
    }
    .actions {
      display: flex;
      align-items: center;
      gap: var(--sf-space-3);
    }
    .result {
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-2);
      flex: 1;
      min-width: 0;
    }
  `,
})
export class ConnectorOperationComponent {
  readonly connector = input.required<Connector>();

  private readonly api = inject(ConnectorsApi);
  private readonly org = inject(OrgContextService);
  private readonly dialogs = inject(DialogService);

  protected readonly operations = OPERATIONS;
  protected readonly formatDuration = formatDuration;
  protected readonly employee = signal<EmployeeRefLike | null>(null);
  protected operation: OperationRequest['operation'] = 'get_user';
  protected readonly busy = signal(false);
  protected readonly result = signal<OperationResponse | null>(null);
  protected readonly error = signal<ApiError | null>(null);

  protected async run(): Promise<void> {
    const employee = this.employee();
    if (!employee) return;
    const op = OPERATIONS.find((o) => o.value === this.operation)!;
    if (op.changes) {
      const ok = await this.dialogs.confirm({
        title: `Run ${op.value} now?`,
        message: `This changes ${employee.full_name}'s account in ${this.connector().name} immediately.`,
        confirmLabel: 'Run operation',
      });
      if (!ok) return;
    }
    this.busy.set(true);
    this.result.set(null);
    this.error.set(null);
    this.api
      .runOperation(this.org.orgId(), this.connector().id, {
        employee_id: employee.id,
        operation: op.value,
      })
      .subscribe({
        next: (r) => {
          this.busy.set(false);
          this.result.set(r);
        },
        error: (e: unknown) => {
          this.busy.set(false);
          this.error.set(ApiError.from(e));
        },
      });
  }
}
