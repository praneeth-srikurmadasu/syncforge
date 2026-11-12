import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ConflictDetail } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { ConflictDetailComponent } from './conflict-detail.component';

const CONFLICT: ConflictDetail = {
  id: 'cf1',
  employee_id: 'e1',
  connector_id: 'c1',
  field: 'department',
  syncforge_value: 'Engineering',
  external_value: 'Finance',
  authoritative_source: 'syncforge',
  severity: 'medium',
  status: 'open',
  employee_version: 1,
  times_detected: 1,
  first_detected_at: '2026-11-12T10:00:00Z',
  last_detected_at: '2026-11-12T10:00:00Z',
  resolved_at: null,
  resolutions: [],
};

async function setup(permissions: string[]) {
  TestBed.configureTestingModule({
    imports: [ConflictDetailComponent],
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      {
        provide: OrgContextService,
        useValue: { orgId: () => 'o1', can: (p: string) => permissions.includes(p) },
      },
    ],
  });
  const fixture = TestBed.createComponent(ConflictDetailComponent);
  fixture.componentRef.setInput('id', 'cf1');
  const http = TestBed.inject(HttpTestingController);
  fixture.detectChanges();
  http.expectOne('/api/v1/organizations/o1/conflicts/cf1').flush(CONFLICT);
  http.expectOne('/api/v1/organizations/o1/connectors?limit=100').flush({
    items: [{ id: 'c1', name: 'payroll' }],
    total: 1,
    limit: 100,
    offset: 0,
  });
  http
    .expectOne((r) => r.url === '/api/v1/organizations/o1/members')
    .flush({ items: [], total: 0, limit: 100, offset: 0 });
  await fixture.whenStable();
  return { fixture, http, el: fixture.nativeElement as HTMLElement };
}

function pick(el: HTMLElement, text: string) {
  const label = [...el.querySelectorAll('label.choice')].find((l) => l.textContent?.includes(text));
  label!.querySelector('input')!.dispatchEvent(new Event('change'));
}

function submitButton(el: HTMLElement): HTMLButtonElement {
  return [...el.querySelectorAll('button')].find((b) =>
    /Resolve|Dismiss conflict/.test(b.textContent ?? ''),
  )!;
}

describe('ConflictDetailComponent', () => {
  it('requires override and a note to decide against the policy', async () => {
    const { fixture, http, el } = await setup(['conflicts:resolve', 'employees:write']);
    pick(el, "Use payroll's value");
    await fixture.whenStable();
    expect(el.textContent).toContain('Decide against the policy');
    expect(submitButton(el).disabled).toBe(true);

    const override = el.querySelector<HTMLInputElement>('.sf-alert--warning input[type=checkbox]')!;
    override.click();
    const note = el.querySelector<HTMLTextAreaElement>('#cf-note')!;
    note.value = 'Payroll is right this time';
    note.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(submitButton(el).disabled).toBe(false);

    submitButton(el).click();
    const req = http.expectOne('/api/v1/organizations/o1/conflicts/cf1/resolve');
    expect(req.request.body).toEqual({
      resolution: 'use_external',
      override: true,
      note: 'Payroll is right this time',
    });
  });

  it('sends the policy decision without override', async () => {
    const { fixture, http, el } = await setup(['conflicts:resolve']);
    pick(el, "Keep SyncForge's value");
    await fixture.whenStable();
    expect(el.textContent).not.toContain('Decide against the policy');
    submitButton(el).click();
    const req = http.expectOne('/api/v1/organizations/o1/conflicts/cf1/resolve');
    expect(req.request.body).toEqual({ resolution: 'use_syncforge', override: false, note: null });
  });

  it('explains that adopting into the employee record needs employees:write', async () => {
    const { fixture, el } = await setup(['conflicts:resolve']);
    pick(el, "Use payroll's value");
    await fixture.whenStable();
    expect(el.textContent).toContain('needs permission to edit employees');
    expect(submitButton(el).disabled).toBe(true);
  });

  it('shows no decision panel without conflicts:resolve', async () => {
    const { el } = await setup([]);
    expect(el.querySelector('label.choice')).toBeNull();
  });
});
