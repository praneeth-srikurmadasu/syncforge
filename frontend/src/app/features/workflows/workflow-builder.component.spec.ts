import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { OrgContextService } from '../../core/org/org-context.service';
import { WorkflowBuilderComponent } from './workflow-builder.component';

const CONNECTORS = {
  items: [
    { id: 'c-slack', name: 'slack', connector_type: 'slack', status: 'connected' },
    { id: 'c-pay', name: 'payroll', connector_type: 'payroll', status: 'disconnected' },
  ],
  total: 2,
  limit: 100,
  offset: 0,
};

async function setup() {
  TestBed.configureTestingModule({
    imports: [WorkflowBuilderComponent],
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: OrgContextService, useValue: { orgId: () => 'o1', can: () => true } },
    ],
  });
  const fixture = TestBed.createComponent(WorkflowBuilderComponent);
  const http = TestBed.inject(HttpTestingController);
  fixture.detectChanges();
  http.expectOne('/api/v1/organizations/o1/connectors?limit=100').flush(CONNECTORS);
  await fixture.whenStable();
  return { fixture, http, el: fixture.nativeElement as HTMLElement };
}

function click(el: HTMLElement, text: string) {
  const button = [...el.querySelectorAll('button')].find((b) => b.textContent?.includes(text));
  button!.click();
}

function choose(el: HTMLElement, selector: string, value: string) {
  const select = el.querySelector<HTMLSelectElement>(selector)!;
  select.value = value;
  select.dispatchEvent(new Event('change'));
}

describe('WorkflowBuilderComponent', () => {
  it('suggests the operation for the trigger and refuses duplicate steps', async () => {
    const { fixture, http, el } = await setup();
    choose(el, '#wf-trigger', 'employee.terminated');
    await fixture.whenStable();
    click(el, 'Add step');
    click(el, 'Add step');
    await fixture.whenStable();
    const ops = [...el.querySelectorAll<HTMLSelectElement>('select[id^=step-op-]')].map(
      (s) => s.value,
    );
    expect(ops).toEqual(['deactivate_user', 'deactivate_user']);

    const conns = el.querySelectorAll<HTMLSelectElement>('select[id^=step-conn-]');
    for (const s of conns) {
      s.value = 'c-slack';
      s.dispatchEvent(new Event('change'));
    }
    const name = el.querySelector<HTMLInputElement>('#wf-name')!;
    name.value = 'Offboarding';
    name.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    click(el, 'Create workflow');
    await fixture.whenStable();
    expect(el.textContent).toContain('Each connector and operation can appear only once.');
    http.verify(); // nothing was sent
  });

  it('sends the trigger and the ordered steps, then opens the workflow', async () => {
    const { fixture, http, el } = await setup();
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const name = el.querySelector<HTMLInputElement>('#wf-name')!;
    name.value = 'Onboarding';
    name.dispatchEvent(new Event('input'));
    click(el, 'Add step');
    click(el, 'Add step');
    await fixture.whenStable();
    const conns = el.querySelectorAll<HTMLSelectElement>('select[id^=step-conn-]');
    conns[0].value = 'c-slack';
    conns[0].dispatchEvent(new Event('change'));
    conns[1].value = 'c-pay';
    conns[1].dispatchEvent(new Event('change'));
    await fixture.whenStable();
    // a disconnected connector is flagged, since activation would be refused
    expect(el.textContent).toContain('Disconnected');
    el.querySelector<HTMLButtonElement>('button[aria-label="Move step 2 up"]')!.click();
    await fixture.whenStable();
    click(el, 'Create workflow');
    const req = http.expectOne('/api/v1/organizations/o1/workflows');
    expect(req.request.body).toEqual({
      name: 'Onboarding',
      description: null,
      trigger_event_type: 'employee.created',
      steps: [
        { connector_id: 'c-pay', operation: 'create_user' },
        { connector_id: 'c-slack', operation: 'create_user' },
      ],
    });
    req.flush({ id: 'w1', name: 'Onboarding', version: 1 });
    expect(navigate).toHaveBeenCalledWith(['/o', 'o1', 'workflows', 'w1']);
    http.verify();
  });
});
