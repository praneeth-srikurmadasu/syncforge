import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';
import { ApiError } from '../../core/api/api-error';
import { AuthApi } from '../../core/api/auth.api';
import { SessionService } from '../../core/auth/session.service';
import { applyServerErrors, controlError } from '../../shared/forms';
import { PasswordFieldComponent, passwordStrength } from '../../shared/ui/password-field.component';
import { toSignal } from '@angular/core/rxjs-interop';

function passwordsMatch(group: AbstractControl): ValidationErrors | null {
  const password = group.get('password')?.value;
  const confirm = group.get('confirm');
  if (confirm && confirm.value && password !== confirm.value) {
    confirm.setErrors({ ...(confirm.errors ?? {}), mismatch: true });
  } else if (confirm?.errors?.['mismatch']) {
    const rest = { ...confirm.errors };
    delete rest['mismatch'];
    confirm.setErrors(Object.keys(rest).length ? rest : null);
  }
  return null;
}

type Field = 'full_name' | 'email' | 'password' | 'confirm';

@Component({
  selector: 'sf-register',
  imports: [ReactiveFormsModule, RouterLink, PasswordFieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1>Create your account</h1>
    <p class="lede">After signing up you can create an organization or be added to one.</p>

    @if (error(); as err) {
      <div class="sf-alert sf-alert--danger" role="alert">
        <div>
          {{ err.status === 409 ? 'An account with this email already exists.' : err.message }}
          @for (issue of extraIssues(); track issue) {
            <div>{{ issue }}</div>
          }
          @if (err.requestId) {
            <code class="rid">Request {{ err.requestId }}</code>
          }
        </div>
      </div>
    }

    <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
      <div class="sf-field">
        <label for="full_name">Full name</label>
        <input id="full_name" class="sf-input" formControlName="full_name" autocomplete="name" />
        @if (err('full_name', 'Full name'); as m) {
          <span class="sf-field__error">{{ m }}</span>
        }
      </div>
      <div class="sf-field">
        <label for="email">Work email</label>
        <input
          id="email"
          class="sf-input"
          type="email"
          formControlName="email"
          autocomplete="email"
        />
        @if (err('email', 'Email'); as m) {
          <span class="sf-field__error">{{ m }}</span>
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
            autocomplete="new-password"
            aria-describedby="password-hint"
          />
        </sf-password-field>
        @if (err('password', 'Password'); as m) {
          <span class="sf-field__error">{{ m }}</span>
        } @else {
          <div class="sf-field__hint strength" id="password-hint" aria-live="polite">
            <span
              >At least 8 characters, not a common password and not your email name. A longer
              passphrase is stronger than symbols.</span
            >
            @if (password()) {
              <span class="meter" [attr.data-level]="strength()">
                <span class="bars" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
                Strength: {{ strengthLabel() }}
              </span>
            }
          </div>
        }
      </div>
      <div class="sf-field">
        <label for="confirm">Confirm password</label>
        <sf-password-field>
          <input
            id="confirm"
            class="sf-input"
            type="password"
            formControlName="confirm"
            autocomplete="new-password"
          />
        </sf-password-field>
        @if (err('confirm', 'Confirmation'); as m) {
          <span class="sf-field__error">{{ m }}</span>
        }
      </div>
      <button type="submit" class="sf-btn sf-btn--primary submit" [disabled]="busy()">
        {{ busy() ? 'Creating account…' : 'Create account' }}
      </button>
    </form>
    <p class="alt">Already registered? <a routerLink="/login">Sign in</a></p>
  `,
  styleUrl: './auth-form.scss',
  styles: `
    .strength {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .meter {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .bars {
      display: inline-flex;
      gap: 3px;
    }
    .bars i {
      width: 22px;
      height: 4px;
      border-radius: 2px;
      background: var(--sf-border-strong);
    }
    [data-level='weak'] .bars i:nth-child(-n + 1) {
      background: var(--sf-danger);
    }
    [data-level='fair'] .bars i:nth-child(-n + 2) {
      background: var(--sf-warning);
    }
    [data-level='good'] .bars i:nth-child(-n + 3) {
      background: var(--sf-info);
    }
    [data-level='strong'] .bars i {
      background: var(--sf-success);
    }
  `,
})
export class RegisterComponent {
  private readonly api = inject(AuthApi);
  private readonly session = inject(SessionService);
  private readonly router = inject(Router);

  protected readonly form = inject(FormBuilder).nonNullable.group(
    {
      full_name: ['', [Validators.required, Validators.maxLength(200)]],
      email: ['', [Validators.required, Validators.email]],
      password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(128)]],
      confirm: ['', [Validators.required]],
    },
    { validators: passwordsMatch },
  );
  protected readonly password = toSignal(this.form.controls.password.valueChanges, {
    initialValue: '',
  });
  protected readonly strength = computed(() => passwordStrength(this.password()));
  protected readonly strengthLabel = computed(
    () => ({ weak: 'too short', fair: 'fair', good: 'good', strong: 'strong' })[this.strength()],
  );
  protected readonly busy = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly extraIssues = signal<string[]>([]);

  protected err(name: Field, label: string): string | null {
    return controlError(this.form.controls[name], label);
  }

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    const { full_name, email, password } = this.form.getRawValue();
    this.api
      .register({ full_name: full_name.trim(), email, password })
      .pipe(switchMap(() => this.session.login(email, password)))
      .subscribe({
        next: () => void this.router.navigateByUrl('/'),
        error: (e: unknown) => {
          const apiError = ApiError.from(e);
          this.busy.set(false);
          this.error.set(apiError);
          this.extraIssues.set(applyServerErrors(this.form, apiError));
        },
      });
  }
}
