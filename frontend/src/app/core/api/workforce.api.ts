import { HttpClient, HttpResourceRequest } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { PageQuery, etag, orgUrl, query } from './http-util';
import {
  Department,
  Employee,
  EmployeeCreate,
  EmployeeSort,
  EmployeeUpdate,
  EmploymentStatus,
  Page,
} from './models';

export interface EmployeeQuery extends PageQuery {
  search?: string;
  department_id?: string;
  manager_id?: string;
  employment_status?: EmploymentStatus | '';
  location?: string;
  joined_from?: string;
  joined_to?: string;
  include_archived?: boolean;
  sort?: EmployeeSort;
}

@Injectable({ providedIn: 'root' })
export class EmployeesApi {
  private readonly http = inject(HttpClient);

  listRequest(orgId: string, q: EmployeeQuery): HttpResourceRequest {
    return { url: orgUrl(orgId, 'employees'), params: query(q) };
  }

  list(orgId: string, q: EmployeeQuery): Observable<Page<Employee>> {
    return this.http.get<Page<Employee>>(orgUrl(orgId, 'employees'), { params: query(q) });
  }

  getRequest(orgId: string, id: string): HttpResourceRequest {
    return { url: orgUrl(orgId, 'employees', id) };
  }

  get(orgId: string, id: string): Observable<Employee> {
    return this.http.get<Employee>(orgUrl(orgId, 'employees', id));
  }

  /** `idempotencyKey` makes a retried submit safe (the API returns the first result). */
  create(orgId: string, body: EmployeeCreate, idempotencyKey: string): Observable<Employee> {
    return this.http.post<Employee>(orgUrl(orgId, 'employees'), body, {
      headers: { 'Idempotency-Key': idempotencyKey },
    });
  }

  update(orgId: string, id: string, body: EmployeeUpdate, version: number): Observable<Employee> {
    return this.http.patch<Employee>(orgUrl(orgId, 'employees', id), body, {
      headers: { 'If-Match': etag(version) },
    });
  }

  terminate(
    orgId: string,
    id: string,
    version: number,
    terminationDate: string | null,
  ): Observable<Employee> {
    return this.http.post<Employee>(
      orgUrl(orgId, 'employees', id, 'terminate'),
      terminationDate ? { termination_date: terminationDate } : null,
      { headers: { 'If-Match': etag(version) } },
    );
  }

  archive(orgId: string, id: string, version: number): Observable<void> {
    return this.http.delete<void>(orgUrl(orgId, 'employees', id), {
      headers: { 'If-Match': etag(version) },
    });
  }
}

@Injectable({ providedIn: 'root' })
export class DepartmentsApi {
  private readonly http = inject(HttpClient);

  listRequest(orgId: string, page: PageQuery = { limit: 100 }): HttpResourceRequest {
    return { url: orgUrl(orgId, 'departments'), params: query(page) };
  }

  list(orgId: string, page: PageQuery = { limit: 100 }): Observable<Page<Department>> {
    return this.http.get<Page<Department>>(orgUrl(orgId, 'departments'), {
      params: query(page),
    });
  }

  create(orgId: string, name: string): Observable<Department> {
    return this.http.post<Department>(orgUrl(orgId, 'departments'), { name });
  }

  rename(orgId: string, id: string, name: string): Observable<Department> {
    return this.http.patch<Department>(orgUrl(orgId, 'departments', id), { name });
  }

  delete(orgId: string, id: string): Observable<void> {
    return this.http.delete<void>(orgUrl(orgId, 'departments', id));
  }
}
