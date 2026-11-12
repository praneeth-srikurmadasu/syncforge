import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { OrganizationsApi } from '../../core/api/organizations.api';
import { ROLE_LABELS } from '../../core/auth/permissions';
import { SessionService } from '../../core/auth/session.service';
import { OrgContextService } from '../../core/org/org-context.service';
import { ThemePreference, ThemeService } from '../../core/theme/theme.service';
import { ToastService } from '../../core/toast/toast.service';
import { formatDateTime } from '../../core/util/format';
import { controlError } from '../../shared/forms';
import { BadgeComponent } from '../../shared/ui/badge.component';
import { CopyIdComponent } from '../../shared/ui/copy-id.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { RecentSignInsComponent } from './recent-sign-ins.component';

@Component({
  selector: 'sf-settings',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    CopyIdComponent,
    TimeComponent,
    RecentSignInsComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-page-header title="Settings" />

      @if (org.organization(); as o) {
        <section class="sf-card">
          <div class="sf-card__header"><h2 class="sf-card__title">Organization</h2></div>
          <div class="sf-card__body body">
            @if (org.can('org:update')) {
              <form class="rename" (submit)="$event.preventDefault(); rename()">
                <div class="sf-field grow">
                  <label for="st-name">Name</label>
                  <input id="st-name" class="sf-input" [formControl]="name" />
                  @if (controlError(name, 'Name'); as m) {
                    <span class="sf-field__error">{{ m }}</span>
                  } @else if (renameError(); as err) {
                    <span class="sf-field__error">{{ err.message }}</span>
                  }
                </div>
                <button
                  type="submit"
                  class="sf-btn sf-btn--primary"
                  [disabled]="busy() || name.invalid || name.value.trim() === o.name"
                >
                  Save name
                </button>
              </form>
            }
            <dl class="sf-dl">
              @if (!org.can('org:update')) {
                <dt>Name</dt>
                <dd>{{ o.name }}</dd>
              }
              <dt>Short name</dt>
              <dd>
                <code>{{ o.slug }}</code>
                <span class="sf-faint">(fixed when the organization was created)</span>
              </dd>
              <dt>Your role</dt>
              <dd>{{ roleLabel() }}</dd>
              <dt>Created</dt>
              <dd>{{ formatDateTime(o.created_at) }}</dd>
              <dt>ID</dt>
              <dd><sf-id [value]="o.id" [short]="false" /></dd>
            </dl>
          </div>
        </section>
      }

      @if (session.user(); as u) {
        <section class="sf-card">
          <div class="sf-card__header"><h2 class="sf-card__title">Your account</h2></div>
          <div class="sf-card__body body">
            <dl class="sf-dl">
              <dt>Name</dt>
              <dd>{{ u.full_name }}</dd>
              <dt>Email</dt>
              <dd>{{ u.email }}</dd>
              <dt>Account type</dt>
              <dd>
                @if (u.is_superadmin) {
                  <sf-badge tone="accent">Super admin</sf-badge>
                } @else {
                  Standard
                }
              </dd>
              <dt>Organizations</dt>
              <dd>
                <ul class="orgs">
                  @for (m of u.memberships; track m.organization_id) {
                    <li>
                      <a [routerLink]="['/o', m.organization_id, 'dashboard']">{{
                        m.organization_name
                      }}</a>
                      <span class="sf-faint">{{ roleLabels[m.role] }}</span>
                    </li>
                  }
                </ul>
              </dd>
              <dt>Session ends</dt>
              <dd>
                @if (session.expiresAt(); as at) {
                  <sf-time [value]="isoOf(at)" />
                  <span class="sf-faint"
                    >(sessions last 30 minutes; there is no automatic renewal)</span
                  >
                }
              </dd>
            </dl>
            <p class="sf-faint small">
              Changing your name or password is not available yet: the API has no endpoint for it.
            </p>
          </div>
        </section>
      }

      <sf-recent-sign-ins />

      <section class="sf-card">
        <div class="sf-card__header"><h2 class="sf-card__title">Appearance</h2></div>
        <div class="sf-card__body">
          <div class="themes" role="radiogroup" aria-label="Theme">
            @for (t of themes; track t.value) {
              <label class="theme" [class.selected]="theme.preference() === t.value">
                <input
                  type="radio"
                  name="theme"
                  [checked]="theme.preference() === t.value"
                  (change)="theme.set(t.value)"
                />
                <span>
                  <strong>{{ t.label }}</strong>
                  <span class="sf-muted d">{{ t.description }}</span>
                </span>
              </label>
            }
          </div>
          <p class="sf-faint small">Saved in this browser only.</p>
        </div>
      </section>

      <section class="sf-card">
        <div class="sf-card__header"><h2 class="sf-card__title">Sign out</h2></div>
        <div class="sf-card__body signout">
          <span class="sf-muted">Ends this session on the server and in this tab.</span>
          <button type="button" class="sf-btn" (click)="signOut()">Sign out</button>
        </div>
      </section>
    </div>
  `,
  styles: `
    .sf-page {
      max-width: 900px;
    }
    .body {
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-4);
    }
    .rename {
      display: flex;
      align-items: flex-start;
      gap: var(--sf-space-3);
    }
    .rename button {
      margin-top: 24px;
    }
    .grow {
      flex: 1;
      max-width: 420px;
    }
    .orgs {
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .orgs li {
      display: flex;
      gap: var(--sf-space-2);
    }
    .themes {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--sf-space-2);
    }
    .theme {
      display: flex;
      gap: var(--sf-space-3);
      padding: var(--sf-space-3) var(--sf-space-4);
      border: 1px solid var(--sf-border);
      border-radius: var(--sf-radius-md);
      cursor: pointer;
    }
    .theme input {
      accent-color: var(--sf-accent);
      margin-top: 3px;
    }
    .theme.selected {
      border-color: var(--sf-accent);
      background: var(--sf-accent-soft);
    }
    .d {
      display: block;
      font-size: var(--sf-text-sm);
    }
    .small {
      margin-top: var(--sf-space-2);
      font-size: var(--sf-text-xs);
    }
    .signout {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--sf-space-3);
    }
    @media (max-width: 720px) {
      .themes {
        grid-template-columns: minmax(0, 1fr);
      }
    }
  `,
})
export class SettingsComponent {
  protected readonly org = inject(OrgContextService);
  protected readonly session = inject(SessionService);
  protected readonly theme = inject(ThemeService);
  private readonly api = inject(OrganizationsApi);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  protected readonly roleLabels = ROLE_LABELS;
  protected readonly controlError = controlError;
  protected readonly formatDateTime = formatDateTime;

  protected readonly themes: { value: ThemePreference; label: string; description: string }[] = [
    { value: 'dark', label: 'Dark', description: 'The default.' },
    { value: 'light', label: 'Light', description: 'Bright surfaces.' },
    { value: 'system', label: 'System', description: 'Follow the operating system.' },
  ];

  protected readonly name = new FormControl(this.org.organization()?.name ?? '', {
    nonNullable: true,
    validators: [Validators.required, Validators.maxLength(200)],
  });
  protected readonly busy = signal(false);
  protected readonly renameError = signal<ApiError | null>(null);

  protected readonly roleLabel = computed(() => {
    const role = this.org.role();
    if (role) return ROLE_LABELS[role];
    return this.session.isSuperadmin() ? 'Super admin (no membership)' : '-';
  });

  protected isoOf(epochMs: number): string {
    return new Date(epochMs).toISOString();
  }

  protected rename(): void {
    const value = this.name.value.trim();
    if (!value) return;
    this.busy.set(true);
    this.renameError.set(null);
    this.api.rename(this.org.orgId(), value).subscribe({
      next: (updated) => {
        this.busy.set(false);
        this.org.update(updated);
        // organization names shown in the switcher come from the user's memberships
        this.session.reloadUser().subscribe({
          error: (e: unknown) => this.toast.error(e, 'Could not refresh your organizations'),
        });
        this.toast.success('Organization renamed');
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.renameError.set(ApiError.from(e));
      },
    });
  }

  protected signOut(): void {
    this.session.logout().subscribe(({ revoked, error }) => {
      this.org.clear();
      if (!revoked && error)
        this.toast.error(error, 'Signed out here, but the server did not confirm');
      void this.router.navigate(['/login']);
    });
  }
}
