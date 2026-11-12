import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ApiError } from '../../core/api/api-error';
import { Department, Employee, EmployeeCreate, EmployeeUpdate, Page } from '../../core/api/models';
import { DepartmentsApi, EmployeesApi } from '../../core/api/workforce.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { todayIso } from '../../core/util/format';
import { applyServerErrors, controlError } from '../../shared/forms';
import { DialogFrameComponent } from '../../shared/ui/dialog';
import {
  EmployeePickerComponent,
  EmployeeRefLike,
} from '../../shared/ui/employee-picker.component';

export interface EmployeeFormData {
  mode: 'create' | 'edit';
  employee?: Employee;
}

type Field =
  | 'first_name'
  | 'last_name'
  | 'email'
  | 'employee_number'
  | 'department_id'
  | 'designation'
  | 'location'
  | 'joining_date'
  | 'employment_status';

const LABELS: Record<Field, string> = {
  first_name: 'First name',
  last_name: 'Last name',
  email: 'Email',
  employee_number: 'Employee number',
  department_id: 'Department',
  designation: 'Designation',
  location: 'Location',
  joining_date: 'Joining date',
  employment_status: 'Status',
};

/** Create or edit an employee. Edits are sent with If-Match, so a concurrent change is detected. */
@Component({
  selector: 'sf-employee-form-dialog',
  imports: [ReactiveFormsModule, DialogFrameComponent, EmployeePickerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './employee-form.dialog.html',
  styles: `
    .sf-alert {
      margin-bottom: var(--sf-space-4);
      flex-direction: column;
      gap: 4px;
    }
    .rid {
      font-size: var(--sf-text-xs);
      color: var(--sf-text-faint);
    }
  `,
})
export class EmployeeFormDialogComponent {
  protected readonly data = inject<EmployeeFormData>(DIALOG_DATA);
  private readonly ref = inject<DialogRef<Employee>>(DialogRef);
  private readonly api = inject(EmployeesApi);
  private readonly org = inject(OrgContextService);

  private readonly departmentsApi = inject(DepartmentsApi);
  protected readonly departments = httpResource<Page<Department>>(() =>
    this.departmentsApi.listRequest(this.org.orgId()),
  );

  private employee = this.data.employee;
  /** One key per dialog: a repeated submit of the same new employee cannot create two. */
  private readonly idempotencyKey = crypto.randomUUID();

  protected readonly form = inject(FormBuilder).nonNullable.group({
    first_name: [this.employee?.first_name ?? '', [Validators.required, Validators.maxLength(100)]],
    last_name: [this.employee?.last_name ?? '', [Validators.required, Validators.maxLength(100)]],
    email: [this.employee?.email ?? '', [Validators.required, Validators.email]],
    employee_number: [
      this.employee?.employee_number ?? '',
      [Validators.required, Validators.maxLength(50)],
    ],
    department_id: [this.employee?.department?.id ?? ''],
    designation: [this.employee?.designation ?? '', [Validators.maxLength(150)]],
    location: [this.employee?.location ?? '', [Validators.maxLength(150)]],
    joining_date: [this.employee?.joining_date ?? todayIso(), [Validators.required]],
    employment_status: [
      (this.employee?.employment_status === 'on_leave' ? 'on_leave' : 'active') as
        'active' | 'on_leave',
    ],
  });
  protected readonly manager = signal<EmployeeRefLike | null>(this.employee?.manager ?? null);
  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly extraIssues = signal<string[]>([]);

  protected err(name: Field): string | null {
    return controlError(this.form.controls[name], LABELS[name]);
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    const v = this.form.getRawValue();
    const values = {
      first_name: v.first_name.trim(),
      last_name: v.last_name.trim(),
      email: v.email.trim(),
      employee_number: v.employee_number.trim(),
      department_id: v.department_id || null,
      designation: v.designation.trim() || null,
      location: v.location.trim() || null,
      joining_date: v.joining_date,
      employment_status: v.employment_status,
      manager_id: this.manager()?.id ?? null,
    };

    let request;
    if (this.employee) {
      const changes = this.changes(values);
      if (Object.keys(changes).length === 0) {
        this.ref.close(); // nothing changed: no request, no events
        return;
      }
      request = this.api.update(this.org.orgId(), this.employee.id, changes, this.employee.version);
    } else {
      request = this.api.create(this.org.orgId(), values as EmployeeCreate, this.idempotencyKey);
    }

    request.subscribe({
      next: (saved) => this.ref.close(saved),
      error: (e: unknown) => {
        const apiError = ApiError.from(e);
        this.busy.set(false);
        this.error.set(apiError);
        this.extraIssues.set(applyServerErrors(this.form, apiError));
      },
    });
  }

  /** Only fields that changed are sent, so an edit never overwrites unrelated fields. */
  private changes(values: Record<string, string | null>): EmployeeUpdate {
    const e = this.employee!;
    const current: Record<string, string | null> = {
      first_name: e.first_name,
      last_name: e.last_name,
      email: e.email,
      employee_number: e.employee_number,
      department_id: e.department?.id ?? null,
      designation: e.designation,
      location: e.location,
      joining_date: e.joining_date,
      employment_status: e.employment_status,
      manager_id: e.manager?.id ?? null,
    };
    const changed: Record<string, string | null> = {};
    for (const [key, value] of Object.entries(values)) {
      if (current[key] !== value) changed[key] = value;
    }
    return changed as EmployeeUpdate;
  }

  /** After a 412, load the latest version and show it, discarding the stale edit. */
  protected reloadLatest(): void {
    if (!this.employee) return;
    this.busy.set(true);
    this.api.get(this.org.orgId(), this.employee.id).subscribe({
      next: (latest) => {
        this.employee = latest;
        this.form.reset({
          first_name: latest.first_name,
          last_name: latest.last_name,
          email: latest.email,
          employee_number: latest.employee_number,
          department_id: latest.department?.id ?? '',
          designation: latest.designation ?? '',
          location: latest.location ?? '',
          joining_date: latest.joining_date,
          employment_status: latest.employment_status === 'on_leave' ? 'on_leave' : 'active',
        });
        this.manager.set(latest.manager);
        this.error.set(null);
        this.busy.set(false);
      },
      error: (e: unknown) => {
        this.error.set(ApiError.from(e));
        this.busy.set(false);
      },
    });
  }

  protected close(): void {
    this.ref.close();
  }
}
