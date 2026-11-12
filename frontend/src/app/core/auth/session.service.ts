import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, firstValueFrom, map, of, switchMap, tap } from 'rxjs';
import { ApiError } from '../api/api-error';
import { AuthApi } from '../api/auth.api';
import { Me } from '../api/models';

const STORAGE_KEY = 'sf.session';

interface StoredSession {
  token: string;
  expiresAt: number; // epoch milliseconds
}

/** Why a session ended without the user signing out - shown on the login screen. */
export type SessionEndReason = 'expired' | 'revoked' | 'invalid' | 'signed_out';

/**
 * The signed-in user's session.
 *
 * The API issues a short-lived bearer token (no refresh token, no cookie). It is held in
 * memory and mirrored to sessionStorage so a reload keeps the user signed in; the copy is
 * per tab and disappears when the tab closes. This is a convenience, not XSS protection:
 * script running in the page could read the token either way. See
 * docs/PHASE_8_FRONTEND_ARCHITECTURE.md for the trade-off.
 */
@Injectable({ providedIn: 'root' })
export class SessionService {
  private readonly api = inject(AuthApi);

  private readonly stored = signal<StoredSession | null>(null);
  readonly user = signal<Me | null>(null);
  readonly endReason = signal<SessionEndReason | null>(null);

  readonly token = computed(() => this.stored()?.token ?? null);
  readonly expiresAt = computed(() => this.stored()?.expiresAt ?? null);
  readonly isAuthenticated = computed(() => this.stored() !== null && this.user() !== null);
  readonly isSuperadmin = computed(() => this.user()?.is_superadmin ?? false);
  readonly memberships = computed(() => this.user()?.memberships ?? []);

  /** Restores a session saved in this tab. Called once at startup. */
  async restore(): Promise<void> {
    const saved = readStorage();
    if (!saved) return;
    if (saved.expiresAt <= Date.now()) {
      this.clear('expired');
      return;
    }
    try {
      const me = await firstValueFrom(this.api.me(saved.token));
      this.install(saved, me);
    } catch (error) {
      const apiError = ApiError.from(error);
      // A rejected token ends the session. If the API is unreachable the session cannot be
      // verified either; it is cleared and the login screen reports the connection problem.
      this.clear(apiError.status === 401 ? reasonFor(apiError.code) : null);
    }
  }

  login(email: string, password: string): Observable<Me> {
    return this.api.login(email, password).pipe(
      switchMap((token) => {
        const session = {
          token: token.access_token,
          expiresAt: Date.now() + token.expires_in * 1000,
        };
        return this.api.me(session.token).pipe(tap((me) => this.install(session, me)));
      }),
    );
  }

  /** Reloads the user's memberships (after creating an organization or a role change). */
  reloadUser(): Observable<Me> {
    return this.api.me().pipe(tap((me) => this.user.set(me)));
  }

  /**
   * Revokes the token on the server, then clears the local session either way. Emits
   * whether the server confirmed the revocation, so the caller can tell the user if not.
   */
  logout(): Observable<{ revoked: boolean; error: ApiError | null }> {
    if (!this.token()) return of({ revoked: true, error: null });
    return this.api.logout().pipe(
      map(() => ({ revoked: true, error: null })),
      catchError((error: unknown) => of({ revoked: false, error: ApiError.from(error) })),
      tap(() => this.clear('signed_out')),
    );
  }

  /** Ends the session after the API rejected the token (called by the error interceptor). */
  expire(code: string): void {
    this.clear(reasonFor(code));
  }

  private install(session: StoredSession, me: Me): void {
    this.stored.set(session);
    this.user.set(me);
    this.endReason.set(null);
    writeStorage(session);
  }

  private clear(reason: SessionEndReason | null): void {
    this.stored.set(null);
    this.user.set(null);
    this.endReason.set(reason);
    writeStorage(null);
  }
}

function reasonFor(code: string): SessionEndReason {
  if (code === 'token_expired') return 'expired';
  if (code === 'token_revoked') return 'revoked';
  return 'invalid';
}

function readStorage(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<StoredSession>;
    return typeof value.token === 'string' && typeof value.expiresAt === 'number'
      ? { token: value.token, expiresAt: value.expiresAt }
      : null;
  } catch {
    return null; // storage unavailable or corrupt: behave as signed out
  }
}

function writeStorage(session: StoredSession | null): void {
  try {
    if (session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (privacy modes); the in-memory session still works.
  }
}
