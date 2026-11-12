import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { ApiError } from '../api/api-error';
import { authInterceptor, errorInterceptor } from './interceptors';
import { SessionService } from './session.service';

describe('HTTP interceptors', () => {
  let http: HttpClient;
  let controller: HttpTestingController;
  let session: SessionService;
  let router: Router;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor, errorInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    session = TestBed.inject(SessionService);
    router = TestBed.inject(Router);
    // sign in through the public API
    session.login('a@example.com', 'pw').subscribe();
    controller.expectOne('/api/v1/auth/login').flush({ access_token: 'tok', expires_in: 1800 });
    controller.expectOne('/api/v1/auth/me').flush({
      id: 'u',
      email: 'a@example.com',
      full_name: 'A',
      is_active: true,
      is_superadmin: false,
      created_at: '2026-01-01T00:00:00Z',
      memberships: [],
    });
  });

  afterEach(() => controller.verify());

  it('sends the token to the SyncForge API only', () => {
    http.get('/api/v1/organizations').subscribe();
    http.get('https://example.org/data').subscribe();
    expect(controller.expectOne('/api/v1/organizations').request.headers.get('Authorization')).toBe(
      'Bearer tok',
    );
    expect(
      controller.expectOne('https://example.org/data').request.headers.has('Authorization'),
    ).toBe(false);
  });

  it('turns failures into ApiError without hiding them', () => {
    let caught: unknown;
    http.get('/api/v1/organizations/x').subscribe({ error: (e) => (caught = e) });
    controller.expectOne('/api/v1/organizations/x').flush(
      {
        error: {
          code: 'permission_denied',
          message: 'Not allowed.',
          details: null,
          request_id: 'r9',
        },
      },
      { status: 403, statusText: 'Forbidden' },
    );
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).code).toBe('permission_denied');
    expect(session.isAuthenticated()).toBe(true); // a 403 does not end the session
  });

  it('ends the session on 401 and returns to the login screen', () => {
    const navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    http.get('/api/v1/organizations').subscribe({ error: () => undefined });
    controller.expectOne('/api/v1/organizations').flush(
      {
        error: {
          code: 'token_expired',
          message: 'Access token has expired.',
          details: null,
          request_id: 'r',
        },
      },
      { status: 401, statusText: 'Unauthorized' },
    );
    expect(session.isAuthenticated()).toBe(false);
    expect(session.endReason()).toBe('expired');
    expect(navigate).toHaveBeenCalledWith(['/login'], expect.anything());
  });
});
