import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  Router,
  RouterStateSnapshot,
  UrlTree,
  provideRouter,
} from '@angular/router';
import { signal } from '@angular/core';
import { OrgContextService } from '../org/org-context.service';
import { authGuard, permissionGuard } from './guards';
import { SessionService } from './session.service';

describe('route guards', () => {
  const authenticated = signal(false);
  const allowed = new Set<string>();

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: SessionService, useValue: { isAuthenticated: authenticated } },
        {
          provide: OrgContextService,
          useValue: { can: (p: string) => allowed.has(p), orgId: () => 'o1' },
        },
      ],
    });
  });

  function run(guard: typeof authGuard, data: Record<string, unknown> = {}, url = '/o/o1/x') {
    const route = { data } as unknown as ActivatedRouteSnapshot;
    const state = { url } as RouterStateSnapshot;
    return TestBed.runInInjectionContext(() => guard(route, state));
  }

  it('sends signed-out users to the login screen with the page to return to', () => {
    authenticated.set(false);
    const result = run(authGuard) as UrlTree;
    expect(TestBed.inject(Router).serializeUrl(result)).toBe('/login?returnUrl=%2Fo%2Fo1%2Fx');
  });

  it('lets signed-in users through', () => {
    authenticated.set(true);
    expect(run(authGuard)).toBe(true);
  });

  it('redirects to the forbidden screen when the role lacks the permission', () => {
    allowed.clear();
    const result = run(permissionGuard, { permission: 'audit:read' }) as UrlTree;
    expect(TestBed.inject(Router).serializeUrl(result)).toBe('/o/o1/forbidden');
    allowed.add('audit:read');
    expect(run(permissionGuard, { permission: 'audit:read' })).toBe(true);
  });
});
