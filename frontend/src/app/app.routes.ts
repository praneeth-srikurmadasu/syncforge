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
