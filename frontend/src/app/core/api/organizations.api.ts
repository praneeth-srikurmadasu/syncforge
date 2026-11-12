import { HttpClient, HttpResourceRequest } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { API_BASE, PageQuery, orgUrl, query } from './http-util';
import { Member, Organization, OrganizationRole, Page } from './models';

@Injectable({ providedIn: 'root' })
export class OrganizationsApi {
  private readonly http = inject(HttpClient);

  listRequest(page: PageQuery = { limit: 100 }): HttpResourceRequest {
    return { url: `${API_BASE}/organizations`, params: query(page) };
  }

  get(orgId: string): Observable<Organization> {
    return this.http.get<Organization>(orgUrl(orgId));
  }

  create(name: string, slug?: string): Observable<Organization> {
    return this.http.post<Organization>(`${API_BASE}/organizations`, { name, slug: slug || null });
  }

  rename(orgId: string, name: string): Observable<Organization> {
    return this.http.patch<Organization>(orgUrl(orgId), { name });
  }

  membersRequest(orgId: string, page: PageQuery): HttpResourceRequest {
    return { url: orgUrl(orgId, 'members'), params: query(page) };
  }

  addMember(orgId: string, email: string, role: OrganizationRole): Observable<Member> {
    return this.http.post<Member>(orgUrl(orgId, 'members'), { email, role });
  }

  changeRole(orgId: string, userId: string, role: OrganizationRole): Observable<Member> {
    return this.http.patch<Member>(orgUrl(orgId, 'members', userId), { role });
  }

  removeMember(orgId: string, userId: string): Observable<void> {
    return this.http.delete<void>(orgUrl(orgId, 'members', userId));
  }

  /** Used where a full list is needed (e.g. resolving actor names); capped at 100. */
  listMembers(orgId: string): Observable<Page<Member>> {
    return this.http.get<Page<Member>>(orgUrl(orgId, 'members'), {
      params: query({ limit: 100 }),
    });
  }
}
