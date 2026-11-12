import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { SessionService } from '../../core/auth/session.service';
import { controlError, safeReturnUrl } from '../../shared/forms';
import { PasswordFieldComponent } from '../../shared/ui/password-field.component';

const END_MESSAGES: Record<string, string> = {
  expired: 'Your session expired. Sign in again to continue.',
  revoked: 'Your session was signed out. Sign in again to continue.',
  invalid: 'Your session is no longer valid. Sign in again to continue.',
};

@Component({
  selector: 'sf-login',
  imports: [ReactiveFormsModule, RouterLink, PasswordFieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1>Sign in</h1>
    <p class="lede">Use the account you registered with SyncForge.</p>

    @if (endMessage()) {
      <div class="sf-alert sf-alert--info" role="status">{{ endMessage() }}</div>
    }
    @if (error(); as err) {
      <div class="sf-alert sf-alert--danger" role="alert">
        <div>
          {{ err.status === 401 ? 'The email or password is incorrect.' : err.message }}
          @if (err.requestId && err.status !== 401) {
            <code class="rid">Request {{ err.requestId }}</code>
          }
        </div>
      </div>
    }

    <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
      <div class="sf-field">
        <label for="email">Email</label>
        <input
          id="email"
          class="sf-input"
          type="email"
          formControlName="email"
          autocomplete="username"
          [attr.aria-invalid]="!!err('email', 'Email')"
          aria-describedby="email-error"
        />
        @if (err('email', 'Email'); as message) {
          <span class="sf-field__error" id="email-error">{{ message }}</span>
        }
      </div>
      <div class="sf-field">
        <label for="password">Password</label>
        <sf-password-field>
          <input
            id="password"
            class="sf-input"
            type="password"
            formControlName="password"
            autocomplete="current-password"
            [attr.aria-invalid]="!!err('password', 'Password')"
            aria-describedby="password-error"
          />
        </sf-password-field>
        @if (err('password', 'Password'); as message) {
          <span class="sf-field__error" id="password-error">{{ message }}</span>
        }
      </div>
      <button type="submit" class="sf-btn sf-btn--primary submit" [disabled]="busy()">
        {{ busy() ? 'Signing in…' : 'Sign in' }}
      </button>
    </form>
    <p class="alt">No account yet? <a routerLink="/register">Create one</a></p>
  `,
  styleUrl: './auth-form.scss',
})
export class LoginComponent {
  private readonly session = inject(SessionService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly form = inject(FormBuilder).nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.maxLength(128)]],
  });
  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly endMessage = computed(() => {
    const reason = this.session.endReason();
    return reason ? (END_MESSAGES[reason] ?? null) : null;
  });

  protected err(name: 'email' | 'password', label: string): string | null {
    return controlError(this.form.controls[name], label);
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    const { email, password } = this.form.getRawValue();
    this.session.login(email, password).subscribe({
      next: () => {
        const target = safeReturnUrl(this.route.snapshot.queryParamMap.get('returnUrl')) ?? '/';
        void this.router.navigateByUrl(target);
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.error.set(ApiError.from(e));
      },
    });
  }
}
