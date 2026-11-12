import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiError } from '../../core/api/api-error';
import { Employee } from '../../core/api/models';
import { EmployeesApi } from '../../core/api/workforce.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { todayIso } from '../../core/util/format';
import { DialogFrameComponent } from '../../shared/ui/dialog';

/** Termination is final in SyncForge; it triggers the offboarding workflows. */
@Component({
  selector: 'sf-terminate-dialog',
  imports: [FormsModule, DialogFrameComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <sf-dialog [title]="'Terminate ' + employee.full_name">
      <div class="content">
        <p>
          This records an <code>employee.terminated</code> event. Active offboarding workflows then
          deactivate the person's accounts in connected applications. Their direct reports move to
          their manager. Termination cannot be undone; a rehire is a new employee record.
        </p>
        @if (error(); as err) {
          <div class="sf-alert sf-alert--danger" role="alert">
            {{
              err.status === 412
                ? 'This employee changed after you opened the page. Close this dialog and reload before terminating.'
                : err.message
            }}
          </div>
        }
        <div class="sf-field">
          <label for="term-date">Last working day</label>
          <input
            id="term-date"
            class="sf-input"
            type="date"
            [min]="employee.joining_date"
            [(ngModel)]="date"
          />
        </div>
        <div class="sf-field">
          <label for="term-confirm"
            >Type <code>{{ employee.employee_number }}</code> to confirm</label
          >
          <input id="term-confirm" class="sf-input" autocomplete="off" [(ngModel)]="typed" />
        </div>
      </div>
      <ng-container footer>
        <button type="button" class="sf-btn" (click)="ref.close()">Cancel</button>
        <button
          type="button"
          class="sf-btn sf-btn--danger"
          [disabled]="busy() || typed !== employee.employee_number || !date"
          (click)="terminate()"
        >
          {{ busy() ? 'Terminating…' : 'Terminate employee' }}
        </button>
      </ng-container>
    </sf-dialog>
  `,
  styles: `
    .content {
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-4);
    }
    p {
      color: var(--sf-text-muted);
    }
  `,
})
export class TerminateDialogComponent {
  protected readonly employee = inject<Employee>(DIALOG_DATA);
  protected readonly ref = inject<DialogRef<Employee>>(DialogRef);
  private readonly api = inject(EmployeesApi);
  private readonly org = inject(OrgContextService);

  protected date = todayIso();
  protected typed = '';
  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);

  protected terminate(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api
      .terminate(this.org.orgId(), this.employee.id, this.employee.version, this.date)
      .subscribe({
        next: (updated) => this.ref.close(updated),
        error: (e: unknown) => {
          this.busy.set(false);
          this.error.set(ApiError.from(e));
        },
      });
  }
}
