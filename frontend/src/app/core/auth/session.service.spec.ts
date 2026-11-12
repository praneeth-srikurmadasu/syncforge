import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Me } from '../api/models';
import { authInterceptor, errorInterceptor } from './interceptors';
import { SessionService } from './session.service';

const ME: Me = {
  id: 'u1',
  email: 'ada@example.com',
  full_name: 'Ada Admin',
  is_active: true,
  is_superadmin: false,
  created_at: '2026-01-01T00:00:00Z',
  memberships: [
    {
      organization_id: 'o1',
      organization_name: 'Acme',
      organization_slug: 'acme',
      role: 'org_admin',
    },
  ],
};

@Component({ template: '' })
class Blank {}

describe('SessionService', () => {
  let session: SessionService;
  let http: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'login', component: Blank }]),
        provideHttpClient(withInterceptors([authInterceptor, errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    session = TestBed.inject(SessionService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function signIn(): void {
    session.login('ada@example.com', 'pw').subscribe();
    http.expectOne('/api/v1/auth/login').flush({ access_token: 'tok', expires_in: 1800 });
    const me = http.expectOne('/api/v1/auth/me');
    expect(me.request.headers.get('Authorization')).toBe('Bearer tok');
    me.flush(ME);
  }

  it('signs in, loads the user and keeps the token for this tab', () => {
    signIn();
    expect(session.isAuthenticated()).toBe(true);
    expect(session.memberships()[0].organization_id).toBe('o1');
    const stored = JSON.parse(sessionStorage.getItem('sf.session') ?? '{}');
    expect(stored.token).toBe('tok');
    expect(stored.expiresAt).toBeGreaterThan(Date.now());
  });

  it('revokes the token on sign-out and clears the session', () => {
    signIn();
    let result: { revoked: boolean } | undefined;
    session.logout().subscribe((r) => (result = r));
    const req = http.expectOne('/api/v1/auth/logout');
    expect(req.request.headers.get('Authorization')).toBe('Bearer tok');
    req.flush(null, { status: 204, statusText: 'No Content' });
    expect(result?.revoked).toBe(true);
    expect(session.isAuthenticated()).toBe(false);
    expect(sessionStorage.getItem('sf.session')).toBeNull();
  });

  it('clears the local session even when the server cannot revoke, and says so', () => {
    signIn();
    let result: { revoked: boolean; error: unknown } | undefined;
    session.logout().subscribe((r) => (result = r));
    http.expectOne('/api/v1/auth/logout').flush(null, { status: 0, statusText: 'Unknown Error' });
    expect(result?.revoked).toBe(false);
    expect(result?.error).toBeTruthy();
    expect(session.isAuthenticated()).toBe(false);
  });

  it('does not restore an expired session', async () => {
    sessionStorage.setItem(
      'sf.session',
      JSON.stringify({ token: 'old', expiresAt: Date.now() - 1 }),
    );
    await session.restore();
    expect(session.isAuthenticated()).toBe(false);
    expect(session.endReason()).toBe('expired');
  });

  it('restores a saved session after verifying it with the API', async () => {
    sessionStorage.setItem(
      'sf.session',
      JSON.stringify({ token: 'tok', expiresAt: Date.now() + 60000 }),
    );
    const done = session.restore();
    http.expectOne('/api/v1/auth/me').flush(ME);
    await done;
    expect(session.isAuthenticated()).toBe(true);
  });

  it('ends the session when the API rejects the token', () => {
    signIn();
    session.reloadUser().subscribe({ error: () => undefined });
    http.expectOne('/api/v1/auth/me').flush(
      {
        error: {
          code: 'token_revoked',
          message: 'Access token has been revoked.',
          details: null,
          request_id: 'r',
        },
      },
      { status: 401, statusText: 'Unauthorized' },
    );
    expect(session.isAuthenticated()).toBe(false);
    expect(session.endReason()).toBe('revoked');
  });
});
