import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { Department, Page } from '../../core/api/models';
import { DepartmentsApi } from '../../core/api/workforce.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { DialogService } from '../../shared/ui/dialog';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

@Component({
  selector: 'sf-departments',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    PageHeaderComponent,
    IconComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-page-header
        title="Departments"
        description="Departments are synchronized to connected applications as part of each employee record."
      />

      @if (org.can('departments:manage')) {
        <form class="sf-card add" (submit)="$event.preventDefault(); create()">
          <div class="sf-field grow">
            <label for="dept-name">New department</label>
            <input
              id="dept-name"
              class="sf-input"
              [formControl]="newName"
              placeholder="e.g. Customer Success"
            />
            @if (createError(); as err) {
              <span class="sf-field__error">{{ err.message }}</span>
            }
          </div>
          <button
            type="submit"
            class="sf-btn sf-btn--primary"
            [disabled]="busy() || newName.invalid"
          >
            <sf-icon name="plus" [size]="14" /> Add department
          </button>
        </form>
      }

      <div class="sf-card">
        @if (departments.error(); as err) {
          <sf-error-state [error]="err" (retry)="departments.reload()" />
        } @else if (departments.value(); as page) {
          @if (page.items.length === 0) {
            <sf-empty-state
              icon="building"
              title="No departments yet"
              message="Add one above, then assign employees to it."
            />
          } @else {
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col" class="sf-cell-num">Employees</th>
                  <th scope="col">Created</th>
                  @if (org.can('departments:manage')) {
                    <th scope="col"><span class="sf-visually-hidden">Actions</span></th>
                  }
                </tr>
              </thead>
              <tbody>
                @for (d of page.items; track d.id) {
                  <tr>
                    <td>
                      @if (editing() === d.id) {
                        <form class="rename" (submit)="$event.preventDefault(); saveRename(d)">
                          <label class="sf-visually-hidden" [for]="'rename-' + d.id"
                            >Department name</label
                          >
                          <input
                            [id]="'rename-' + d.id"
                            class="sf-input"
                            [formControl]="renameControl"
                          />
                          <button
                            type="submit"
                            class="sf-btn sf-btn--sm sf-btn--primary"
                            [disabled]="busy() || renameControl.invalid"
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            class="sf-btn sf-btn--sm"
                            (click)="editing.set(null)"
                          >
                            Cancel
                          </button>
                        </form>
                      } @else {
                        <span class="sf-cell-primary">{{ d.name }}</span>
                      }
                    </td>
                    <td class="sf-cell-num">
                      <a
                        [routerLink]="['/o', org.orgId(), 'employees']"
                        [queryParams]="{ department: d.id }"
                        >{{ d.employee_count }}</a
                      >
                    </td>
                    <td><sf-time [value]="d.created_at" /></td>
                    @if (org.can('departments:manage')) {
                      <td class="actions">
                        <button
                          type="button"
                          class="sf-btn sf-btn--ghost sf-btn--sm"
                          (click)="startRename(d)"
                          [attr.aria-label]="'Rename ' + d.name"
                        >
                          <sf-icon name="pencil" [size]="13" /> Rename
                        </button>
                        <button
                          type="button"
                          class="sf-btn sf-btn--ghost sf-btn--sm"
                          (click)="remove(d)"
                          [disabled]="d.employee_count > 0"
                          [attr.title]="
                            d.employee_count > 0
                              ? 'Move its employees to another department first'
                              : null
                          "
                          [attr.aria-label]="'Delete ' + d.name"
                        >
                          <sf-icon name="trash" [size]="13" /> Delete
                        </button>
                      </td>
                    }
                  </tr>
                }
              </tbody>
            </table>
          }
        } @else {
          <sf-skeleton [rows]="5" />
        }
      </div>
    </div>
  `,
  styles: `
    .add {
      display: flex;
      align-items: flex-end;
      gap: var(--sf-space-3);
      padding: var(--sf-space-4);
    }
    .grow {
      flex: 1;
      max-width: 420px;
    }
    .rename {
      display: flex;
      gap: var(--sf-space-2);
      align-items: center;
    }
    .rename .sf-input {
      max-width: 260px;
      height: 28px;
    }
    .actions {
      text-align: right;
      white-space: nowrap;
    }
  `,
})
export class DepartmentsComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(DepartmentsApi);
  private readonly toast = inject(ToastService);
  private readonly dialogs = inject(DialogService);

  protected readonly departments = httpResource<Page<Department>>(() =>
    this.api.listRequest(this.org.orgId()),
  );
  protected readonly newName = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required, Validators.maxLength(100)],
  });
  protected readonly renameControl = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required, Validators.maxLength(100)],
  });
  protected readonly editing = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly createError = signal<ApiError | null>(null);

  protected create(): void {
    const name = this.newName.value.trim();
    if (!name) return;
    this.busy.set(true);
    this.createError.set(null);
    this.api.create(this.org.orgId(), name).subscribe({
      next: (d) => {
        this.busy.set(false);
        this.newName.reset();
        this.departments.reload();
        this.toast.success(`Added ${d.name}`);
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.createError.set(ApiError.from(e));
      },
    });
  }

  protected startRename(d: Department): void {
    this.renameControl.setValue(d.name);
    this.editing.set(d.id);
  }

  protected saveRename(d: Department): void {
    const name = this.renameControl.value.trim();
    if (!name || name === d.name) {
      this.editing.set(null);
      return;
    }
    this.busy.set(true);
    this.api.rename(this.org.orgId(), d.id, name).subscribe({
      next: () => {
        this.busy.set(false);
        this.editing.set(null);
        this.departments.reload();
        this.toast.success(`Renamed to ${name}`);
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.toast.error(e, 'Rename failed');
      },
    });
  }

  protected async remove(d: Department): Promise<void> {
    const ok = await this.dialogs.confirm({
      title: `Delete ${d.name}?`,
      message: 'The department is removed. This cannot be undone.',
      confirmLabel: 'Delete department',
      tone: 'danger',
    });
    if (!ok) return;
    this.api.delete(this.org.orgId(), d.id).subscribe({
      next: () => {
        this.departments.reload();
        this.toast.success(`Deleted ${d.name}`);
      },
      // The API refuses (409) while employees - including archived ones - still belong to it.
      error: (e: unknown) => this.toast.error(e, 'Delete failed'),
    });
  }
}
