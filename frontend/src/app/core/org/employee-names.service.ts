import { Injectable, Signal, inject, signal } from '@angular/core';
import { EmployeesApi } from '../api/workforce.api';
import { ApiError } from '../api/api-error';

export interface EmployeeName {
  state: 'loading' | 'ok' | 'missing' | 'error';
  name: string | null;
  number: string | null;
}

/**
 * Event, dead-letter and conflict lists return employee IDs only. Names are fetched once
 * per employee and cached for the organization, so a page of rows costs at most one
 * request per distinct employee.
 */
@Injectable({ providedIn: 'root' })
export class EmployeeNamesService {
  private readonly api = inject(EmployeesApi);
  private orgId: string | null = null;
  private readonly cache = new Map<string, ReturnType<typeof signal<EmployeeName>>>();

  get(orgId: string, employeeId: string): Signal<EmployeeName> {
    if (orgId !== this.orgId) {
      this.cache.clear();
      this.orgId = orgId;
    }
    let entry = this.cache.get(employeeId);
    if (!entry) {
      entry = signal<EmployeeName>({ state: 'loading', name: null, number: null });
      this.cache.set(employeeId, entry);
      const target = entry;
      this.api.get(orgId, employeeId).subscribe({
        next: (e) => target.set({ state: 'ok', name: e.full_name, number: e.employee_number }),
        error: (e: unknown) =>
          target.set({
            state: ApiError.from(e).status === 404 ? 'missing' : 'error',
            name: null,
            number: null,
          }),
      });
    }
    return entry.asReadonly();
  }

  /** Called after an employee is edited, so lists show the new name. */
  forget(employeeId: string): void {
    this.cache.delete(employeeId);
  }
}
