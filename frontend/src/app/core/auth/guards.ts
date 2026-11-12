import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { OrgContextService } from '../org/org-context.service';
import { Permission } from './permissions';
import { SessionService } from './session.service';

/** Signed-in users only; others go to the login screen and come back afterwards. */
export const authGuard: CanActivateFn = (_route, state) => {
  if (inject(SessionService).isAuthenticated()) return true;
  return inject(Router).createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
};

/** The login and register screens are for signed-out users. */
export const guestGuard: CanActivateFn = () => {
  if (!inject(SessionService).isAuthenticated()) return true;
  return inject(Router).createUrlTree(['/']);
};

/**
 * Loads the organization named in the URL. The API answers 404 for organizations the user
 * does not belong to, so membership is verified by the backend, not assumed here.
 */
export const organizationGuard: CanActivateFn = async (route) => {
  const orgId = route.paramMap.get('orgId');
  const router = inject(Router);
  if (!orgId) return router.createUrlTree(['/']);
  const outcome = await inject(OrgContextService).select(orgId);
  if (outcome === 'ok') return true;
  return router.createUrlTree(['/unavailable'], { queryParams: { reason: outcome } });
};

/** Route data `permission` hides screens the role cannot use (the API still enforces it). */
export const permissionGuard: CanActivateFn = (route) => {
  const permission = route.data['permission'] as Permission | undefined;
  const org = inject(OrgContextService);
  if (!permission || org.can(permission)) return true;
  return inject(Router).createUrlTree(['/o', org.orgId(), 'forbidden']);
};

/** `/` lands in the last organization used, the first membership, or onboarding. */
export const homeRedirectGuard: CanActivateFn = () => {
  const session = inject(SessionService);
  const router = inject(Router);
  if (!session.isAuthenticated()) return router.createUrlTree(['/login']);
  const memberships = session.memberships();
  const last = inject(OrgContextService).lastOrganizationId();
  const target = memberships.find((m) => m.organization_id === last) ?? memberships[0];
  if (target) return router.createUrlTree(['/o', target.organization_id, 'dashboard']);
  if (last && session.isSuperadmin()) return router.createUrlTree(['/o', last, 'dashboard']);
  return router.createUrlTree(['/organizations/new']);
};
