import { ROLE_PERMISSIONS, hasPermission } from './permissions';

describe('permissions (mirror of the backend matrix)', () => {
  it('lets viewers read but not change anything', () => {
    expect(hasPermission('viewer', false, 'employees:read')).toBe(true);
    expect(hasPermission('viewer', false, 'conflicts:read')).toBe(true);
    expect(hasPermission('viewer', false, 'employees:write')).toBe(false);
    expect(hasPermission('viewer', false, 'audit:read')).toBe(false);
    expect(hasPermission('viewer', false, 'events:replay')).toBe(false);
  });

  it('lets integration managers operate integrations but not people', () => {
    expect(hasPermission('integration_manager', false, 'connectors:manage')).toBe(true);
    expect(hasPermission('integration_manager', false, 'events:replay')).toBe(true);
    expect(hasPermission('integration_manager', false, 'audit:read')).toBe(true);
    expect(hasPermission('integration_manager', false, 'conflicts:resolve')).toBe(true);
    expect(hasPermission('integration_manager', false, 'employees:write')).toBe(false);
    expect(hasPermission('integration_manager', false, 'members:manage')).toBe(false);
    expect(hasPermission('integration_manager', false, 'policies:manage')).toBe(false);
  });

  it('gives organization admins every permission', () => {
    expect(ROLE_PERMISSIONS.org_admin.size).toBe(18);
  });

  it('gives super admins every permission without a membership', () => {
    expect(hasPermission(null, true, 'policies:manage')).toBe(true);
    expect(hasPermission(null, false, 'org:read')).toBe(false);
  });
});
