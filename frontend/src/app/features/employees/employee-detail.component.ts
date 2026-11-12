import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { Observable, catchError, expand, of, reduce, EMPTY, map } from 'rxjs';
import { ApiError } from '../../core/api/api-error';
import { Employee, ManagerRef, Page } from '../../core/api/models';
import { EmployeesApi } from '../../core/api/workforce.api';
import { EmployeeNamesService } from '../../core/org/employee-names.service';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { formatDate } from '../../core/util/format';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { CopyIdComponent } from '../../shared/ui/copy-id.component';
import { DialogService } from '../../shared/ui/dialog';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TabItem, TabsComponent } from '../../shared/ui/tabs.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { EmployeeActivityComponent } from './employee-activity.component';
import { EmployeeFormData, EmployeeFormDialogComponent } from './employee-form.dialog';
import { TerminateDialogComponent } from './terminate.dialog';

const MAX_CHAIN = 10;

@Component({
  selector: 'sf-employee-detail',
  imports: [
    RouterLink,
    PageHeaderComponent,
    StatusBadgeComponent,
    CopyIdComponent,
    IconComponent,
    TabsComponent,
    TimeComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    EmployeeActivityComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './employee-detail.component.html',
  styleUrl: './employee-detail.component.scss',
})
export class EmployeeDetailComponent {
  readonly id = input.required<string>();

  protected readonly org = inject(OrgContextService);
  private readonly api = inject(EmployeesApi);
  private readonly dialogs = inject(DialogService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly names = inject(EmployeeNamesService);

  protected readonly formatDate = formatDate;
  protected readonly tab = signal('overview');

  protected readonly employee = httpResource<Employee>(() =>
    this.api.getRequest(this.org.orgId(), this.id()),
  );

  protected readonly reports = httpResource<Page<Employee>>(() =>
    this.api.listRequest(this.org.orgId(), { manager_id: this.id(), limit: 50, sort: 'last_name' }),
  );

  /** The management chain above this person, read manager by manager (up to 10 levels). */
  protected readonly chain = rxResource({
    params: () => {
      const e = this.employee.value();
      return e ? { org: this.org.orgId(), manager: e.manager } : undefined;
    },
    stream: ({ params }) => this.managementChain(params.org, params.manager),
  });

  protected readonly tabs = computed<TabItem[]>(() => {
    const tabs: TabItem[] = [
      { id: 'overview', label: 'Overview' },
      { id: 'reports', label: 'Direct reports', count: this.reports.value()?.total ?? null },
      { id: 'events', label: 'Sync events' },
      { id: 'conflicts', label: 'Conflicts' },
    ];
    if (this.org.can('audit:read')) tabs.push({ id: 'history', label: 'Change history' });
    return tabs;
  });

  protected readonly isTerminated = computed(
    () => this.employee.value()?.employment_status === 'terminated',
  );

  private managementChain(orgId: string, first: ManagerRef | null): Observable<ManagerRef[]> {
    if (!first) return of([]);
    let depth = 0;
    return of(first).pipe(
      expand((ref) => {
        if (!ref || ++depth >= MAX_CHAIN) return EMPTY;
        return this.api.get(orgId, ref.id).pipe(
          map((m) => m.manager),
          catchError(() => of(null)),
        );
      }),
      reduce<ManagerRef | null, ManagerRef[]>((acc, ref) => (ref ? [...acc, ref] : acc), []),
      map((list) => list.reverse()),
    );
  }

  protected edit(employee: Employee): void {
    const ref = this.dialogs.open<Employee, EmployeeFormData, EmployeeFormDialogComponent>(
      EmployeeFormDialogComponent,
      { mode: 'edit', employee },
      true,
    );
    ref.closed.subscribe((saved) => {
      if (!saved) return;
      this.employee.set(saved);
      this.names.forget(saved.id);
      this.reports.reload();
      this.toast.success('Changes saved');
    });
  }

  protected terminate(employee: Employee): void {
    const ref = this.dialogs.open<Employee, Employee, TerminateDialogComponent>(
      TerminateDialogComponent,
      employee,
    );
    ref.closed.subscribe((updated) => {
      if (!updated) return;
      this.employee.set(updated);
      this.reports.reload();
      this.toast.success(`${updated.full_name} terminated. Offboarding workflows will run.`);
    });
  }

  protected async archive(employee: Employee): Promise<void> {
    const ok = await this.dialogs.confirm({
      title: `Archive ${employee.full_name}?`,
      message:
        'Archived employees are hidden from lists unless "Include archived" is selected. The record and its history are kept.',
      confirmLabel: 'Archive',
      tone: 'danger',
    });
    if (!ok) return;
    this.api.archive(this.org.orgId(), employee.id, employee.version).subscribe({
      next: () => {
        this.toast.success(`${employee.full_name} archived`);
        void this.router.navigate(['/o', this.org.orgId(), 'employees']);
      },
      error: (e: unknown) => this.toast.error(e, 'Archive failed'),
    });
  }

  protected errorOf(e: unknown): ApiError {
    return ApiError.from(e);
  }
}
