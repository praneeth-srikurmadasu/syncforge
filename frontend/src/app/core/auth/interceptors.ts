import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { ApiError } from '../api/api-error';
import { API_BASE } from '../api/http-util';
import { SessionService } from './session.service';

/** Adds the bearer token to SyncForge API calls (never to other origins). */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const token = inject(SessionService).token();
  if (!token || !req.url.startsWith(API_BASE) || req.headers.has('Authorization')) {
    return next(req);
  }
  return next(req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }));
};

/**
 * Turns every failed response into an ApiError. A 401 on an authenticated call means the
 * token is no longer accepted: the session ends and the user returns to the login screen,
 * coming back to the same page after signing in. Errors are re-thrown, never swallowed.
 */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const session = inject(SessionService);
  const router = inject(Router);
  return next(req).pipe(
    catchError((error: unknown) => {
      const apiError = ApiError.from(error);
      const authenticated = req.headers.has('Authorization') || session.token() !== null;
      const isLogin = req.url.endsWith('/auth/login');
      if (apiError.status === 401 && authenticated && !isLogin && session.token()) {
        session.expire(apiError.code);
        const returnUrl = router.url.startsWith('/login') ? undefined : router.url;
        void router.navigate(['/login'], { queryParams: { returnUrl } });
      }
      return throwError(() => apiError);
    }),
  );
};
