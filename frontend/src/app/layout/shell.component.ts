import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { ROLE_LABELS } from '../core/auth/permissions';
import { SessionService } from '../core/auth/session.service';
import { OrgContextService } from '../core/org/org-context.service';
import { ThemeService } from '../core/theme/theme.service';
import { ToastService } from '../core/toast/toast.service';
import { initials } from '../core/util/format';
import { IconComponent } from '../shared/ui/icon.component';
import { BrandMarkComponent } from './brand-mark.component';
import { NAV } from './nav';

const EXPIRY_WARNING_MS = 3 * 60 * 1000;

/** Application frame for an organization: sidebar, top bar, session notices, content. */
@Component({
  selector: 'sf-shell',
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    IconComponent,
    BrandMarkComponent,
    CdkMenu,
    CdkMenuItem,
    CdkMenuTrigger,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  protected readonly session = inject(SessionService);
  protected readonly org = inject(OrgContextService);
  protected readonly theme = inject(ThemeService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  protected readonly navOpen = signal(false);
  protected readonly now = signal(Date.now());

  protected readonly nav = computed(() => {
    this.org.organization(); // re-evaluate when the organization (and role) changes
    return NAV.map((group) => ({
      ...group,
      items: group.items.filter((item) => this.org.can(item.permission)),
    })).filter((group) => group.items.length > 0);
  });

  protected readonly roleLabel = computed(() => {
    const role = this.org.role();
    if (role) return ROLE_LABELS[role];
    return this.session.isSuperadmin() ? 'Super admin' : '';
  });

  protected readonly userInitials = computed(() => initials(this.session.user()?.full_name));

  protected readonly otherMemberships = computed(() =>
    this.session.memberships().filter((m) => m.organization_id !== this.org.orgId()),
  );

  protected readonly minutesLeft = computed(() => {
    const expiresAt = this.session.expiresAt();
    if (!expiresAt) return null;
    const left = expiresAt - this.now();
    return left > 0 && left <= EXPIRY_WARNING_MS ? Math.max(1, Math.ceil(left / 60000)) : null;
  });

  constructor() {
    const timer = setInterval(() => this.now.set(Date.now()), 15000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.navOpen.set(false));
  }

  protected switchTo(orgId: string): void {
    void this.router.navigate(['/o', orgId, 'dashboard']);
  }

  /** Employees are the only searchable entity in the API; the search opens the directory. */
  protected searchEmployees(event: Event, term: string): void {
    event.preventDefault();
    void this.router.navigate(['/o', this.org.orgId(), 'employees'], {
      queryParams: term.trim() ? { search: term.trim() } : {},
    });
  }

  protected signOut(): void {
    this.session.logout().subscribe(({ revoked, error }) => {
      this.org.clear();
      if (!revoked && error) {
        this.toast.error(error, 'Signed out on this device, but the server did not confirm');
      }
      void this.router.navigate(['/login']);
    });
  }
}
