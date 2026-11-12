import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { switchMap, map } from 'rxjs';
import { ApiError } from '../../core/api/api-error';
import { OrganizationsApi } from '../../core/api/organizations.api';
import { SessionService } from '../../core/auth/session.service';
import { ToastService } from '../../core/toast/toast.service';
import { applyServerErrors, controlError } from '../../shared/forms';
import { BrandMarkComponent } from '../../layout/brand-mark.component';

@Component({
  selector: 'sf-create-organization',
  imports: [ReactiveFormsModule, RouterLink, BrandMarkComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="card sf-card">
      <sf-brand-mark [size]="32" />
      <h1>Create an organization</h1>
      <p class="sf-muted">
        An organization holds your employees, connectors and workflows. You become its
        administrator. To join an existing organization instead, ask one of its administrators to
        add {{ session.user()?.email }}.
      </p>

      @if (error(); as err) {
        <div class="sf-alert sf-alert--danger" role="alert">
          {{ err.message }}
          @for (issue of extraIssues(); track issue) {
            <div>{{ issue }}</div>
          }
        </div>
      }

      <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <div class="sf-field">
          <label for="org-name">Name</label>
          <input id="org-name" class="sf-input" formControlName="name" placeholder="Acme Corp" />
          @if (err('name', 'Name'); as m) {
            <span class="sf-field__error">{{ m }}</span>
          }
        </div>
        <div class="sf-field">
          <label for="org-slug">Short name (optional)</label>
          <input id="org-slug" class="sf-input sf-mono" formControlName="slug" placeholder="acme" />
          @if (err('slug', 'Short name'); as m) {
            <span class="sf-field__error">{{ m }}</span>
          } @else {
            <span class="sf-field__hint">
              Lowercase letters, numbers and hyphens. Generated from the name if left empty.
            </span>
          }
        </div>
        <div class="actions">
          @if (session.memberships().length) {
            <a class="sf-btn" routerLink="/">Cancel</a>
          }
          <button type="submit" class="sf-btn sf-btn--primary" [disabled]="busy()">
            {{ busy() ? 'Creating…' : 'Create organization' }}
          </button>
        </div>
      </form>
      @if (!session.memberships().length) {
        <button type="button" class="sf-btn sf-btn--ghost signout" (click)="signOut()">
          Sign out
        </button>
      }
    </div>
  `,
  styles: `
    :host {
      display: grid;
      place-items: center;
      min-height: 100vh;
      padding: var(--sf-space-4);
    }
    .card {
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-4);
      width: min(480px, 100%);
      padding: var(--sf-space-6);
    }
    form {
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-4);
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: var(--sf-space-2);
    }
    .signout {
      align-self: flex-start;
    }
  `,
})
export class CreateOrganizationComponent {
  private readonly api = inject(OrganizationsApi);
  protected readonly session = inject(SessionService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);

  protected readonly form = inject(FormBuilder).nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(200)]],
    slug: ['', [Validators.maxLength(63), Validators.pattern(/^[a-z0-9]+(-[a-z0-9]+)*$/)]],
  });
  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly extraIssues = signal<string[]>([]);

  protected err(name: 'name' | 'slug', label: string): string | null {
    return controlError(this.form.controls[name], label);
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    const { name, slug } = this.form.getRawValue();
    this.api
      .create(name.trim(), slug || undefined)
      .pipe(switchMap((org) => this.session.reloadUser().pipe(map(() => org))))
      .subscribe({
        next: (org) => {
          this.toast.success(`Created ${org.name}`);
          void this.router.navigate(['/o', org.id, 'dashboard']);
        },
        error: (e: unknown) => {
          const apiError = ApiError.from(e);
          this.busy.set(false);
          this.error.set(apiError);
          this.extraIssues.set(applyServerErrors(this.form, apiError));
        },
      });
  }

  protected signOut(): void {
    this.session.logout().subscribe(({ revoked, error }) => {
      if (!revoked && error) this.toast.error(error, 'The server did not confirm sign-out');
      void this.router.navigate(['/login']);
    });
  }
}
