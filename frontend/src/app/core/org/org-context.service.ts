import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiError } from '../api/api-error';
import { Organization } from '../api/models';
import { OrganizationsApi } from '../api/organizations.api';
import { Permission, hasPermission } from '../auth/permissions';
import { SessionService } from '../auth/session.service';

const LAST_ORG_KEY = 'sf.lastOrganization';

export type SelectOutcome = 'ok' | 'not_found' | 'error';

/** The organization the user is working in (from the URL) and their role in it. */
@Injectable({ providedIn: 'root' })
export class OrgContextService {
  private readonly api = inject(OrganizationsApi);
  private readonly session = inject(SessionService);

  readonly organization = signal<Organization | null>(null);
  readonly lastError = signal<ApiError | null>(null);

  readonly orgId = computed(() => this.organization()?.id ?? '');
  /** null for a Super Admin acting in an organization without a membership. */
  readonly role = computed(() => this.organization()?.my_role ?? null);

  can(permission: Permission): boolean {
    return hasPermission(this.role(), this.session.isSuperadmin(), permission);
  }

  async select(orgId: string): Promise<SelectOutcome> {
    if (this.organization()?.id === orgId) return 'ok';
    try {
      const org = await firstValueFrom(this.api.get(orgId));
      this.organization.set(org);
      this.lastError.set(null);
      try {
        localStorage.setItem(LAST_ORG_KEY, org.id);
      } catch {
        // not essential
      }
      return 'ok';
    } catch (error) {
      const apiError = ApiError.from(error);
      this.lastError.set(apiError);
      return apiError.status === 404 || apiError.status === 422 ? 'not_found' : 'error';
    }
  }

  /** Applies a rename made on the settings screen without reloading. */
  update(org: Organization): void {
    if (org.id === this.orgId())
      this.organization.update((o) =>
        o ? { ...o, ...org, my_role: org.my_role ?? o.my_role } : org,
      );
  }

  clear(): void {
    this.organization.set(null);
  }

  lastOrganizationId(): string | null {
    try {
      return localStorage.getItem(LAST_ORG_KEY);
    } catch {
      return null;
    }
  }
}
