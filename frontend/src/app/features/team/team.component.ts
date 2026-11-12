import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { Member, OrganizationRole, Page } from '../../core/api/models';
import { OrganizationsApi } from '../../core/api/organizations.api';
import { ROLE_LABELS } from '../../core/auth/permissions';
import { SessionService } from '../../core/auth/session.service';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { controlError } from '../../shared/forms';
import { BadgeComponent } from '../../shared/ui/badge.component';
import { DialogService } from '../../shared/ui/dialog';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

const ROLE_DESCRIPTIONS: Record<OrganizationRole, string> = {
  org_admin: 'Everything, including people, departments, members and policies.',
  integration_manager:
    'Connectors, workflows, replays, conflict resolution and the audit log; reads people.',
  viewer: 'Reads employees, connectors, workflows, events and conflicts.',
};

@Component({
  selector: 'sf-team',
  imports: [
    ReactiveFormsModule,
    PageHeaderComponent,
    BadgeComponent,
    IconComponent,
    PaginationComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-page-header
        title="Team and roles"
        description="People who can sign in to this organization and what their role lets them do."
      />

      <section class="roles" aria-label="Roles">
        @for (r of roles; track r) {
          <div class="role sf-card">
            <strong>{{ roleLabels[r] }}</strong>
            <span class="sf-muted">{{ roleDescriptions[r] }}</span>
          </div>
        }
      </section>

      @if (canManage()) {
        <form class="sf-card add" [formGroup]="form" (ngSubmit)="add()" novalidate>
          <div class="sf-field grow">
            <label for="tm-email">Add a member by email</label>
            <input
              id="tm-email"
              class="sf-input"
              type="email"
              formControlName="email"
              autocomplete="off"
              placeholder="name@company.com"
            />
            @if (controlError(form.controls.email, 'Email'); as m) {
              <span class="sf-field__error">{{ m }}</span>
            } @else if (addError(); as err) {
              <span class="sf-field__error">{{
                err.code === 'user_not_found'
                  ? 'No SyncForge account uses this email. They need to register first; invitations are not available yet.'
                  : err.message
              }}</span>
            } @else {
              <span class="sf-field__hint">The person must already have a SyncForge account.</span>
            }
          </div>
          <div class="sf-field">
            <label for="tm-role">Role</label>
            <select id="tm-role" class="sf-select" formControlName="role">
              @for (r of roles; track r) {
                <option [value]="r">{{ roleLabels[r] }}</option>
              }
            </select>
          </div>
          <button type="submit" class="sf-btn sf-btn--primary" [disabled]="busy()">
            <sf-icon name="user-plus" [size]="14" /> Add member
          </button>
        </form>
      }

      <div class="sf-card">
        @if (members.error(); as err) {
          <sf-error-state [error]="err" (retry)="members.reload()" />
        } @else if (members.value(); as page) {
          @if (page.items.length === 0) {
            <sf-empty-state icon="users" title="No members" />
          } @else {
            <div class="sf-table-wrap">
              <table class="sf-table">
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Role</th>
                    <th scope="col">Joined</th>
                    @if (canManage()) {
                      <th scope="col"><span class="sf-visually-hidden">Actions</span></th>
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (m of page.items; track m.user_id) {
                    <tr>
                      <td>
                        <span class="sf-cell-primary">{{ m.full_name }}</span>
                        @if (m.user_id === myId()) {
                          <sf-badge tone="accent">You</sf-badge>
                        }
                        <span class="sf-faint email">{{ m.email }}</span>
                      </td>
                      <td>
                        @if (canManage()) {
                          <label class="sf-visually-hidden" [for]="'role-' + m.user_id"
                            >Role for {{ m.full_name }}</label
                          >
                          <select
                            [id]="'role-' + m.user_id"
                            class="sf-select role-select"
                            [value]="m.role"
                            (change)="changeRole(m, $any($event.target))"
                          >
                            @for (r of roles; track r) {
                              <option [value]="r" [selected]="r === m.role">
                                {{ roleLabels[r] }}
                              </option>
                            }
                          </select>
                        } @else {
                          {{ roleLabels[m.role] }}
                        }
                      </td>
                      <td><sf-time [value]="m.joined_at" /></td>
                      @if (canManage()) {
                        <td class="actions">
                          <button
                            type="button"
                            class="sf-btn sf-btn--ghost sf-btn--sm"
                            (click)="remove(m)"
                            [attr.aria-label]="'Remove ' + m.full_name"
                          >
                            <sf-icon name="user-minus" [size]="13" /> Remove
                          </button>
                        </td>
                      }
                    </tr>
                  }
                </tbody>
              </table>
            </div>
            <sf-pagination
              [total]="page.total"
              [limit]="page.limit"
              [offset]="page.offset"
              (offsetChange)="offset.set($event)"
            />
          }
        } @else {
          <sf-skeleton [rows]="4" />
        }
      </div>
      <p class="sf-faint small">
        An organization always keeps at least one organization admin; the API refuses changes that
        would remove the last one.
      </p>
    </div>
  `,
  styles: `
    .roles {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--sf-space-3);
    }
    .role {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: var(--sf-space-4);
      font-size: var(--sf-text-sm);
    }
    .add {
      display: flex;
      align-items: flex-start;
      gap: var(--sf-space-3);
      padding: var(--sf-space-4);
      flex-wrap: wrap;
    }
    .add button {
      margin-top: 24px;
    }
    .grow {
      flex: 1 1 320px;
    }
    .email {
      display: block;
      font-size: var(--sf-text-xs);
    }
    .role-select {
      width: 220px;
      height: 30px;
    }
    .actions {
      text-align: right;
    }
    .small {
      font-size: var(--sf-text-xs);
    }
    @media (max-width: 900px) {
      .roles {
        grid-template-columns: minmax(0, 1fr);
      }
    }
  `,
})
export class TeamComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(OrganizationsApi);
  private readonly session = inject(SessionService);
  private readonly toast = inject(ToastService);
  private readonly dialogs = inject(DialogService);
  private readonly router = inject(Router);

  protected readonly roles: OrganizationRole[] = ['org_admin', 'integration_manager', 'viewer'];
  protected readonly roleLabels = ROLE_LABELS;
  protected readonly roleDescriptions = ROLE_DESCRIPTIONS;
  protected readonly controlError = controlError;
  protected readonly myId = computed(() => this.session.user()?.id);
  protected readonly canManage = computed(() => {
    this.org.organization();
    return this.org.can('members:manage');
  });

  protected readonly offset = signal(0);
  protected readonly members = httpResource<Page<Member>>(() =>
    this.api.membersRequest(this.org.orgId(), { limit: 50, offset: this.offset() }),
  );

  protected readonly form = inject(FormBuilder).nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    role: ['viewer' as OrganizationRole],
  });
  protected readonly busy = signal(false);
  protected readonly addError = signal<ApiError | null>(null);

  protected add(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.addError.set(null);
    const { email, role } = this.form.getRawValue();
    this.api.addMember(this.org.orgId(), email.trim(), role).subscribe({
      next: (m) => {
        this.busy.set(false);
        this.form.reset({ email: '', role: 'viewer' });
        this.members.reload();
        this.toast.success(`${m.full_name} added as ${ROLE_LABELS[m.role]}`);
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.addError.set(ApiError.from(e));
      },
    });
  }

  protected async changeRole(m: Member, select: HTMLSelectElement): Promise<void> {
    const role = select.value as OrganizationRole;
    if (role === m.role) return;
    const self = m.user_id === this.myId();
    if (self) {
      const ok = await this.dialogs.confirm({
        title: 'Change your own role?',
        message: `You will become ${ROLE_LABELS[role]} and may lose access to some screens, including this one.`,
        confirmLabel: 'Change my role',
        tone: 'danger',
      });
      if (!ok) {
        select.value = m.role;
        return;
      }
    }
    const orgId = this.org.orgId();
    this.api.changeRole(orgId, m.user_id, role).subscribe({
      next: () => {
        this.toast.success(`${m.full_name} is now ${ROLE_LABELS[role]}`);
        if (self) {
          // Our permissions changed: load the organization (and our role) again.
          this.org.clear();
          this.session.reloadUser().subscribe({
            next: () => void this.router.navigate(['/o', orgId, 'dashboard']),
            error: (e: unknown) => {
              this.toast.error(e, 'Could not reload your account');
              void this.router.navigate(['/o', orgId, 'dashboard']);
            },
          });
        } else {
          this.members.reload();
        }
      },
      error: (e: unknown) => {
        select.value = m.role; // keep showing the role that is actually stored
        this.toast.error(e, 'Role not changed');
      },
    });
  }

  protected async remove(m: Member): Promise<void> {
    const self = m.user_id === this.myId();
    const ok = await this.dialogs.confirm({
      title: self ? 'Leave this organization?' : `Remove ${m.full_name}?`,
      message: self
        ? 'You will lose access to this organization immediately.'
        : `${m.full_name} will no longer be able to sign in to this organization. Their past actions stay in the audit log.`,
      confirmLabel: self ? 'Leave' : 'Remove member',
      tone: 'danger',
    });
    if (!ok) return;
    const orgId = this.org.orgId();
    this.api.removeMember(orgId, m.user_id).subscribe({
      next: () => {
        this.toast.success(self ? 'You left the organization' : `${m.full_name} removed`);
        if (self) {
          this.org.clear();
          this.session.reloadUser().subscribe({
            next: () => void this.router.navigateByUrl('/'),
            error: (e: unknown) => {
              this.toast.error(e, 'Could not reload your account');
              void this.router.navigateByUrl('/');
            },
          });
        } else {
          this.members.reload();
        }
      },
      error: (e: unknown) => this.toast.error(e, 'Not removed'),
    });
  }
}
