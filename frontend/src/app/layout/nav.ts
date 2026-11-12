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
];
