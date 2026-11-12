import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Connector, ConnectorType } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { ConnectorFormDialogComponent } from './connector-form.dialog';

const SLACK: ConnectorType = {
  connector_type: 'slack',
  display_name: 'Slack',
  description: 'Slack SCIM',
  version: '1.0.0',
  auth_type: 'bearer_token',
  simulated: true,
  operations: ['create_user'],
  config_schema: {
    properties: {
      rate_limit_per_minute: {
        anyOf: [{ type: 'integer', minimum: 1, maximum: 10000 }, { type: 'null' }],
        default: null,
        title: 'Rate Limit Per Minute',
      },
    },
  },
  credentials_schema: {
    properties: { token: { type: 'string', format: 'password', minLength: 8, title: 'Token' } },
    required: ['token'],
  },
};

const CONNECTOR = {
  id: 'c1',
  name: 'slack',
  connector_type: 'slack',
  config: { rate_limit_per_minute: 30 },
  status: 'connected',
} as unknown as Connector;

function setup(data: unknown) {
  const close = vi.fn();
  TestBed.configureTestingModule({
    imports: [ConnectorFormDialogComponent],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: DIALOG_DATA, useValue: data },
      { provide: DialogRef, useValue: { close } },
      { provide: OrgContextService, useValue: { orgId: () => 'o1' } },
    ],
  });
  const fixture = TestBed.createComponent(ConnectorFormDialogComponent);
  fixture.detectChanges();
  return {
    fixture,
    close,
    http: TestBed.inject(HttpTestingController),
    el: fixture.nativeElement as HTMLElement,
  };
}

function type(el: HTMLElement, selector: string, value: string) {
  const input = el.querySelector<HTMLInputElement>(selector)!;
  input.value = value;
  input.dispatchEvent(new Event('input'));
}

describe('ConnectorFormDialogComponent', () => {
  it('builds the form from the schema and creates the connector', async () => {
    const { fixture, http, el } = setup({ mode: 'create', type: SLACK });
    await fixture.whenStable();
    expect(el.querySelector('#cred-token')?.getAttribute('type')).toBe('password');
    type(el, '#cf-name', 'Slack HQ');
    type(el, '#cred-token', 'xoxp-mock-local-token');
    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    const req = http.expectOne('/api/v1/organizations/o1/connectors');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      connector_type: 'slack',
      name: 'Slack HQ',
      config: {},
      credentials: { token: 'xoxp-mock-local-token' },
    });
    http.verify();
  });

  it('refuses to submit without the required credential', async () => {
    const { fixture, http, el } = setup({ mode: 'create', type: SLACK });
    await fixture.whenStable();
    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    fixture.detectChanges();
    http.verify(); // no request
    expect(el.textContent).toContain('Token is required.');
  });

  it('sends only credentials when replacing them', async () => {
    const { fixture, http, el } = setup({ mode: 'credentials', type: SLACK, connector: CONNECTOR });
    await fixture.whenStable();
    expect(el.querySelector('#cf-name')).toBeNull();
    type(el, '#cred-token', 'new-token-123');
    el.querySelector('form')!.dispatchEvent(new Event('submit'));
    const req = http.expectOne('/api/v1/organizations/o1/connectors/c1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ credentials: { token: 'new-token-123' } });
    http.verify();
  });

  it('pre-fills current settings when editing them', async () => {
    const { fixture, el } = setup({ mode: 'settings', type: SLACK, connector: CONNECTOR });
    await fixture.whenStable();
    expect(el.querySelector<HTMLInputElement>('#cfg-rate_limit_per_minute')!.value).toBe('30');
    expect(el.querySelector('#cred-token')).toBeNull();
  });
});
