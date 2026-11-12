import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Employee } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { EmployeeFormDialogComponent } from './employee-form.dialog';

const EMPLOYEE: Employee = {
  id: 'e1',
  first_name: 'Ada',
  last_name: 'Lovelace',
  full_name: 'Ada Lovelace',
  email: 'ada@example.com',
  employee_number: 'E-1',
  employment_status: 'active',
  department: { id: 'd1', name: 'Engineering' },
  manager: null,
  designation: 'Engineer',
  location: 'Pune',
  joining_date: '2026-01-05',
  termination_date: null,
  archived_at: null,
  created_at: '2026-01-05T00:00:00Z',
  updated_at: '2026-01-05T00:00:00Z',
  organization_id: 'o1',
  version: 7,
};

function setup(data: unknown) {
  const close = vi.fn();
  TestBed.configureTestingModule({
    imports: [EmployeeFormDialogComponent],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: DIALOG_DATA, useValue: data },
      { provide: DialogRef, useValue: { close } },
      { provide: OrgContextService, useValue: { orgId: () => 'o1' } },
    ],
  });
  const fixture = TestBed.createComponent(EmployeeFormDialogComponent);
  fixture.detectChanges();
  const http = TestBed.inject(HttpTestingController);
  http.expectOne('/api/v1/organizations/o1/departments?limit=100').flush({
    items: [{ id: 'd1', name: 'Engineering', employee_count: 1, created_at: '' }],
    total: 1,
    limit: 100,
    offset: 0,
  });
  return { fixture, http, close, el: fixture.nativeElement as HTMLElement };
}

function type(el: HTMLElement, selector: string, value: string) {
  const input = el.querySelector<HTMLInputElement>(selector)!;
  input.value = value;
  input.dispatchEvent(new Event('input'));
}

describe('EmployeeFormDialogComponent', () => {
  it('sends only the changed fields with If-Match on edit', async () => {
    const { fixture, http, close, el } = setup({ mode: 'edit', employee: EMPLOYEE });
    await fixture.whenStable();
    type(el, '#ef-designation', 'Staff Engineer');
    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    const req = http.expectOne('/api/v1/organizations/o1/employees/e1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.headers.get('If-Match')).toBe('"7"');
    expect(req.request.body).toEqual({ designation: 'Staff Engineer' });
    req.flush({ ...EMPLOYEE, designation: 'Staff Engineer', version: 8 });
    expect(close).toHaveBeenCalledWith(expect.objectContaining({ version: 8 }));
    http.verify();
  });

  it('does not call the API when nothing changed', async () => {
    const { fixture, http, close, el } = setup({ mode: 'edit', employee: EMPLOYEE });
    await fixture.whenStable();
    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    http.verify();
    expect(close).toHaveBeenCalledWith();
  });

  it('creates with an Idempotency-Key that stays the same when retried', async () => {
    const { fixture, http, el } = setup({ mode: 'create' });
    await fixture.whenStable();
    type(el, '#ef-first', 'Grace');
    type(el, '#ef-last', 'Hopper');
    type(el, '#ef-email', 'grace@example.com');
    type(el, '#ef-number', 'E-2');
    const form = el.querySelector('form')!;
    form.dispatchEvent(new Event('submit'));
    const first = http.expectOne('/api/v1/organizations/o1/employees');
    const key = first.request.headers.get('Idempotency-Key');
    expect(key).toBeTruthy();
    first.flush(null, { status: 0, statusText: 'Unknown Error' }); // network failure
    form.dispatchEvent(new Event('submit'));
    const retry = http.expectOne('/api/v1/organizations/o1/employees');
    expect(retry.request.headers.get('Idempotency-Key')).toBe(key);
    expect(retry.request.body).toMatchObject({
      first_name: 'Grace',
      manager_id: null,
      department_id: null,
    });
    http.verify();
  });

  it('shows the concurrent-change message on 412', async () => {
    const { fixture, http, el } = setup({ mode: 'edit', employee: EMPLOYEE });
    await fixture.whenStable();
    type(el, '#ef-location', 'Chennai');
    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    http.expectOne('/api/v1/organizations/o1/employees/e1').flush(
      {
        error: { code: 'version_conflict', message: 'Changed.', details: null, request_id: 'r' },
      },
      { status: 412, statusText: 'Precondition Failed' },
    );
    fixture.detectChanges();
    expect(el.textContent).toContain('Someone else changed this employee');
  });
});
