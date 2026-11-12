import { HttpParams } from '@angular/common/http';

export const API_BASE = '/api/v1';

/** Path under an organization: `/api/v1/organizations/{org}/...`. */
export function orgUrl(orgId: string, ...segments: string[]): string {
  const rest = segments.map((s) => `/${encodeURIComponent(s)}`).join('');
  return `${API_BASE}/organizations/${encodeURIComponent(orgId)}${rest}`;
}

export type QueryValue = string | number | boolean | null | undefined;

/** Query parameters with empty values dropped, so "no filter" sends nothing. */
export function query(values: object): HttpParams {
  let params = new HttpParams();
  for (const [key, value] of Object.entries(values) as [string, QueryValue][]) {
    if (value === null || value === undefined || value === '') continue;
    params = params.set(key, String(value));
  }
  return params;
}

export interface PageQuery {
  limit?: number;
  offset?: number;
}

/** Strong ETag for an employee version, as the API expects in If-Match. */
export function etag(version: number): string {
  return `"${version}"`;
}
