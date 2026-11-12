import { IconName } from '../shared/ui/icon.component';
import { Permission } from '../core/auth/permissions';

export interface NavItem {
  label: string;
  path: string; // relative to /o/:orgId
  icon: IconName;
  permission: Permission;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** Sidebar entries. Each is shown only if the role holds the permission its API needs. */
export const NAV: NavGroup[] = [
  {
    label: 'Overview',
    items: [{ label: 'Dashboard', path: 'dashboard', icon: 'dashboard', permission: 'org:read' }],
  },
  {
    label: 'Workforce',
    items: [
      { label: 'Employees', path: 'employees', icon: 'users', permission: 'employees:read' },
      {
        label: 'Departments',
        path: 'departments',
        icon: 'building',
        permission: 'departments:read',
      },
      {
        label: 'Reporting lines',
        path: 'reporting',
        icon: 'network',
        permission: 'employees:read',
      },
    ],
  },
  {
    label: 'Integrations',
    items: [
      { label: 'Connectors', path: 'connectors', icon: 'plug', permission: 'connectors:read' },
      { label: 'Workflows', path: 'workflows', icon: 'workflow', permission: 'workflows:read' },
      { label: 'Events', path: 'events', icon: 'activity', permission: 'events:read' },
    ],
  },
  {
    label: 'Reliability',
    items: [
      { label: 'Overview', path: 'reliability', icon: 'shield', permission: 'events:read' },
      {
        label: 'Dead-letter queue',
        path: 'dead-letters',
        icon: 'inbox',
        permission: 'events:read',
      },
    ],
  },
  {
    label: 'Governance',
    items: [
      { label: 'Conflicts', path: 'conflicts', icon: 'compare', permission: 'conflicts:read' },
      { label: 'Audit log', path: 'audit', icon: 'file-clock', permission: 'audit:read' },
      { label: 'Team and roles', path: 'team', icon: 'users', permission: 'members:read' },
      { label: 'Settings', path: 'settings', icon: 'settings', permission: 'org:read' },
    ],
  },
];
