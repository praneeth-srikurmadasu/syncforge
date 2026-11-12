import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs';
import { Department, Employee, EmployeeSort, Page } from '../../core/api/models';
import { DepartmentsApi, EmployeeQuery, EmployeesApi } from '../../core/api/workforce.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { formatDate } from '../../core/util/format';
import { useQueryState } from '../../shared/query-state';
import { StatusBadgeComponent } from '../../shared/ui/badge.component';
import { DialogService } from '../../shared/ui/dialog';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { EmployeeFormDialogComponent, EmployeeFormData } from './employee-form.dialog';

const PAGE_SIZE = 25;
const SORTS: { value: EmployeeSort; label: string }[] = [
  { value: 'last_name', label: 'Last name, A-Z' },
  { value: '-last_name', label: 'Last name, Z-A' },
  { value: '-joining_date', label: 'Joined, newest first' },
  { value: 'joining_date', label: 'Joined, oldest first' },
  { value: 'employee_number', label: 'Employee number' },
  { value: '-created_at', label: 'Recently added' },
];

@Component({
  selector: 'sf-employees-list',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    PageHeaderComponent,
    StatusBadgeComponent,
    IconComponent,
    PaginationComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './employees-list.component.html',
  styleUrl: './employees-list.component.scss',
})
export class EmployeesListComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(EmployeesApi);
  private readonly departmentsApi = inject(DepartmentsApi);
  private readonly dialogs = inject(DialogService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  protected readonly q = useQueryState();

  protected readonly sorts = SORTS;
  protected readonly formatDate = formatDate;
  protected readonly search = new FormControl(this.q.get('search'), { nonNullable: true });

  protected readonly query = computed<EmployeeQuery>(() => {
    this.q.params();
    return {
      search: this.q.get('search') || undefined,
      department_id: this.q.get('department') || undefined,
      employment_status: (this.q.get('status') as EmployeeQuery['employment_status']) || undefined,
      location: this.q.get('location') || undefined,
      joined_from: this.q.get('from') || undefined,
      joined_to: this.q.get('to') || undefined,
      include_archived: this.q.get('archived') === 'true' || undefined,
      sort: (this.q.get('sort') as EmployeeSort) || 'last_name',
      limit: PAGE_SIZE,
      offset: this.q.number('offset'),
    };
  });

  protected readonly employees = httpResource<Page<Employee>>(() =>
    this.api.listRequest(this.org.orgId(), this.query()),
  );
  protected readonly departments = httpResource<Page<Department>>(() =>
    this.departmentsApi.listRequest(this.org.orgId()),
  );

  protected readonly hasFilters = computed(() => {
    const q = this.query();
    return !!(
      q.search ||
      q.department_id ||
      q.employment_status ||
      q.location ||
      q.joined_from ||
      q.joined_to ||
      q.include_archived
    );
  });

  constructor() {
    this.search.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed())
      .subscribe((value) => this.q.set({ search: value.trim() }));
  }

  protected setFilter(name: string, event: Event): void {
    const target = event.target as HTMLInputElement | HTMLSelectElement;
    const value =
      target instanceof HTMLInputElement && target.type === 'checkbox'
        ? target.checked
        : target.value;
    this.q.set({ [name]: value });
  }

  protected clearFilters(): void {
    this.search.setValue('', { emitEvent: false });
    this.q.clear();
  }

  protected open(employee: Employee): void {
    void this.router.navigate(['/o', this.org.orgId(), 'employees', employee.id]);
  }

  protected create(): void {
    const ref = this.dialogs.open<Employee, EmployeeFormData, EmployeeFormDialogComponent>(
      EmployeeFormDialogComponent,
      { mode: 'create' },
      true,
    );
    ref.closed.subscribe((created) => {
      if (!created) return;
      this.toast.success(`Added ${created.full_name}. Onboarding workflows will run for them.`);
      void this.router.navigate(['/o', this.org.orgId(), 'employees', created.id]);
    });
  }
}
