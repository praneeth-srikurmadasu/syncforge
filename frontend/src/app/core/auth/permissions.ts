import { OrganizationRole } from '../api/models';

/**
 * Mirror of the backend's ROLE_PERMISSIONS (backend/app/security/authorization.py).
 * It only decides what the interface shows; the API enforces every permission and the
 * interface handles its 403 responses.
 */
export type Permission =
  | 'org:read'
  | 'org:update'
  | 'members:read'
  | 'members:manage'
  | 'employees:read'
  | 'employees:write'
  | 'departments:read'
  | 'departments:manage'
  | 'connectors:read'
  | 'connectors:manage'
  | 'workflows:read'
  | 'workflows:manage'
  | 'events:read'
  | 'events:replay'
  | 'audit:read'
  | 'conflicts:read'
  | 'conflicts:resolve'
  | 'policies:manage';

const VIEWER: readonly Permission[] = [
  'org:read',
  'members:read',
  'employees:read',
  'departments:read',
  'connectors:read',
  'workflows:read',
  'events:read',
  'conflicts:read',
];

const MANAGER: readonly Permission[] = [
  ...VIEWER,
  'connectors:manage',
  'workflows:manage',
  'events:replay',
  'audit:read',
  'conflicts:resolve',
];

const ADMIN: readonly Permission[] = [
  ...MANAGER,
  'org:update',
  'members:manage',
  'employees:write',
  'departments:manage',
  'policies:manage',
];

export const ROLE_PERMISSIONS: Record<OrganizationRole, ReadonlySet<Permission>> = {
  viewer: new Set(VIEWER),
  integration_manager: new Set(MANAGER),
  org_admin: new Set(ADMIN),
};

export const ROLE_LABELS: Record<OrganizationRole, string> = {
  org_admin: 'Organization admin',
  integration_manager: 'Integration manager',
  viewer: 'Viewer',
};

/** Super Admins hold every permission, with or without a membership. */
export function hasPermission(
  role: OrganizationRole | null | undefined,
  superadmin: boolean,
  permission: Permission,
): boolean {
  if (superadmin) return true;
  return role ? ROLE_PERMISSIONS[role].has(permission) : false;
}
