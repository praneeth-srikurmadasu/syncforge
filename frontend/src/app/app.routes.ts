import { Routes } from '@angular/router';
import {
  authGuard,
  guestGuard,
  homeRedirectGuard,
  organizationGuard,
  permissionGuard,
} from './core/auth/guards';
import { NotFoundComponent } from './features/system/system-pages';

export const routes: Routes = [
  { path: '', pathMatch: 'full', canActivate: [homeRedirectGuard], children: [] },
  {
    path: '',
    loadComponent: () =>
      import('./features/auth/auth-layout.component').then((m) => m.AuthLayoutComponent),
    canActivate: [guestGuard],
    children: [
      {
        path: 'login',
        title: 'Sign in · SyncForge',
        loadComponent: () =>
          import('./features/auth/login.component').then((m) => m.LoginComponent),
      },
      {
        path: 'register',
        title: 'Create account · SyncForge',
        loadComponent: () =>
          import('./features/auth/register.component').then((m) => m.RegisterComponent),
      },
    ],
  },
  {
    path: 'organizations/new',
    title: 'Create organization · SyncForge',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/onboarding/create-organization.component').then(
        (m) => m.CreateOrganizationComponent,
      ),
  },
  {
    path: 'unavailable',
    title: 'Organization unavailable · SyncForge',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/system/system-pages').then((m) => m.UnavailableComponent),
  },
  {
    path: 'o/:orgId',
    canActivate: [authGuard, organizationGuard],
    loadComponent: () => import('./layout/shell.component').then((m) => m.ShellComponent),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        title: 'Dashboard · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'org:read' },
        loadComponent: () =>
          import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'employees',
        title: 'Employees · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'employees:read' },
        loadComponent: () =>
          import('./features/employees/employees-list.component').then(
            (m) => m.EmployeesListComponent,
          ),
      },
      {
        path: 'employees/:id',
        title: 'Employee · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'employees:read' },
        loadComponent: () =>
          import('./features/employees/employee-detail.component').then(
            (m) => m.EmployeeDetailComponent,
          ),
      },
      {
        path: 'departments',
        title: 'Departments · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'departments:read' },
        loadComponent: () =>
          import('./features/departments/departments.component').then(
            (m) => m.DepartmentsComponent,
          ),
      },
      {
        path: 'reporting',
        title: 'Reporting lines · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'employees:read' },
        loadComponent: () =>
          import('./features/reporting/reporting.component').then((m) => m.ReportingComponent),
      },
      {
        path: 'connectors',
        title: 'Connectors · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'connectors:read' },
        loadComponent: () =>
          import('./features/connectors/connectors-list.component').then(
            (m) => m.ConnectorsListComponent,
          ),
      },
      {
        path: 'connectors/:id',
        title: 'Connector · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'connectors:read' },
        loadComponent: () =>
          import('./features/connectors/connector-detail.component').then(
            (m) => m.ConnectorDetailComponent,
          ),
      },
      {
        path: 'events',
        title: 'Events · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'events:read' },
        loadComponent: () =>
          import('./features/events/events-list.component').then((m) => m.EventsListComponent),
      },
      {
        path: 'events/:id',
        title: 'Event · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'events:read' },
        loadComponent: () =>
          import('./features/events/event-detail.component').then((m) => m.EventDetailComponent),
      },
      {
        path: 'workflows',
        title: 'Workflows · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'workflows:read' },
        loadComponent: () =>
          import('./features/workflows/workflows-list.component').then(
            (m) => m.WorkflowsListComponent,
          ),
      },
      {
        path: 'workflows/new',
        title: 'New workflow · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'workflows:manage' },
        loadComponent: () =>
          import('./features/workflows/workflow-builder.component').then(
            (m) => m.WorkflowBuilderComponent,
          ),
      },
      {
        path: 'workflows/:id',
        title: 'Workflow · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'workflows:read' },
        loadComponent: () =>
          import('./features/workflows/workflow-detail.component').then(
            (m) => m.WorkflowDetailComponent,
          ),
      },
      {
        path: 'workflows/:id/edit',
        title: 'Edit workflow · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'workflows:manage' },
        loadComponent: () =>
          import('./features/workflows/workflow-builder.component').then(
            (m) => m.WorkflowBuilderComponent,
          ),
      },
      {
        path: 'reliability',
        title: 'Reliability · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'events:read' },
        loadComponent: () =>
          import('./features/reliability/reliability.component').then(
            (m) => m.ReliabilityComponent,
          ),
      },
      {
        path: 'dead-letters',
        title: 'Dead-letter queue · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'events:read' },
        loadComponent: () =>
          import('./features/dead-letters/dead-letters-list.component').then(
            (m) => m.DeadLettersListComponent,
          ),
      },
      {
        path: 'dead-letters/:id',
        title: 'Dead letter · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'events:read' },
        loadComponent: () =>
          import('./features/dead-letters/dead-letter-detail.component').then(
            (m) => m.DeadLetterDetailComponent,
          ),
      },
      {
        path: 'conflicts',
        title: 'Conflicts · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'conflicts:read' },
        loadComponent: () =>
          import('./features/conflicts/conflicts-list.component').then(
            (m) => m.ConflictsListComponent,
          ),
      },
      {
        path: 'conflicts/:id',
        title: 'Conflict · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'conflicts:read' },
        loadComponent: () =>
          import('./features/conflicts/conflict-detail.component').then(
            (m) => m.ConflictDetailComponent,
          ),
      },
      {
        path: 'policies',
        title: 'Policies · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'conflicts:read' },
        loadComponent: () =>
          import('./features/conflicts/policies.component').then((m) => m.PoliciesComponent),
      },
      {
        path: 'audit',
        title: 'Audit log · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'audit:read' },
        loadComponent: () =>
          import('./features/audit/audit-log.component').then((m) => m.AuditLogComponent),
      },
      {
        path: 'team',
        title: 'Team and roles · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'members:read' },
        loadComponent: () => import('./features/team/team.component').then((m) => m.TeamComponent),
      },
      {
        path: 'settings',
        title: 'Settings · SyncForge',
        canActivate: [permissionGuard],
        data: { permission: 'org:read' },
        loadComponent: () =>
          import('./features/settings/settings.component').then((m) => m.SettingsComponent),
      },
      {
        path: 'forbidden',
        title: 'Not permitted · SyncForge',
        loadComponent: () =>
          import('./features/system/system-pages').then((m) => m.ForbiddenComponent),
      },
      { path: '**', component: NotFoundComponent },
    ],
  },
  { path: '**', title: 'Not found · SyncForge', component: NotFoundComponent },
];
