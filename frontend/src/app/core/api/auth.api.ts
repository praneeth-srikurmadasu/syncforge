import { HttpClient, HttpResourceRequest } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_BASE } from './http-util';
import { Me, RegisterRequest, TokenResponse, UserResponse } from './models';

@Injectable({ providedIn: 'root' })
export class AuthApi {
  private readonly http = inject(HttpClient);

  login(email: string, password: string): Observable<TokenResponse> {
    return this.http.post<TokenResponse>(`${API_BASE}/auth/login`, { email, password });
  }

  register(body: RegisterRequest): Observable<UserResponse> {
    return this.http.post<UserResponse>(`${API_BASE}/auth/register`, body);
  }

  /** `token` lets the session check a token before it is installed. */
  me(token?: string): Observable<Me> {
    const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
    return this.http.get<Me>(`${API_BASE}/auth/me`, { headers });
  }

  logout(): Observable<void> {
    return this.http.post<void>(`${API_BASE}/auth/logout`, null);
  }

  /** The signed-in user's own recent sign-ins, failures and sign-outs (newest first). */
  activityRequest(limit = 10): HttpResourceRequest {
    return { url: `${API_BASE}/auth/activity`, params: { limit } };
  }
}
