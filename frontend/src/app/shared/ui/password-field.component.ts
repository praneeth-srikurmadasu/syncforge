import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  inject,
  signal,
} from '@angular/core';
import { IconComponent } from './icon.component';

/**
 * Wraps a native password input: a show/hide button (the input keeps its form binding and
 * autocomplete attribute) and a Caps Lock notice while typing.
 *
 *   <sf-password-field><input type="password" formControlName="password" ... /></sf-password-field>
 */
@Component({
  selector: 'sf-password-field',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(keydown)': 'checkCaps($event)',
    '(keyup)': 'checkCaps($event)',
    '(focusout)': 'capsLock.set(false)',
  },
  template: `
    <div class="wrap">
      <ng-content />
      <button
        type="button"
        class="toggle"
        [attr.aria-label]="visible() ? 'Hide password' : 'Show password'"
        [attr.aria-pressed]="visible()"
        [attr.title]="visible() ? 'Hide password' : 'Show password'"
        (click)="toggle()"
      >
        <sf-icon [name]="visible() ? 'eye-off' : 'eye'" [size]="16" />
      </button>
    </div>
    @if (capsLock()) {
      <span class="caps" role="status">Caps Lock is on</span>
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .wrap {
      position: relative;
    }
    .wrap ::ng-deep input {
      padding-right: 40px;
    }
    .toggle {
      position: absolute;
      top: 50%;
      right: 4px;
      display: grid;
      place-items: center;
      width: 28px;
      height: 28px;
      padding: 0;
      border: none;
      border-radius: var(--sf-radius-sm);
      background: none;
      color: var(--sf-text-muted);
      cursor: pointer;
      transform: translateY(-50%);
    }
    .toggle:hover {
      color: var(--sf-text);
      background: var(--sf-surface-hover);
    }
    .caps {
      font-size: var(--sf-text-xs);
      color: var(--sf-warning);
    }
  `,
})
export class PasswordFieldComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private input: HTMLInputElement | null = null;

  protected readonly visible = signal(false);
  protected readonly capsLock = signal(false);

  constructor() {
    afterNextRender(() => {
      this.input = this.host.nativeElement.querySelector('input');
    });
  }

  protected toggle(): void {
    if (!this.input) return;
    const show = !this.visible();
    this.visible.set(show);
    this.input.type = show ? 'text' : 'password';
    this.input.focus();
  }

  protected checkCaps(event: KeyboardEvent): void {
    if (typeof event.getModifierState === 'function') {
      this.capsLock.set(event.getModifierState('CapsLock'));
    }
  }
}

export type PasswordStrength = 'weak' | 'fair' | 'good' | 'strong';

/**
 * A rough guide shown while choosing a password - length matters most. It is advice only;
 * the API's rule is 8 to 128 characters of any kind.
 */
export function passwordStrength(password: string): PasswordStrength {
  if (password.length < 8) return 'weak';
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) =>
    r.test(password),
  ).length;
  if (password.length >= 16 || (password.length >= 12 && classes >= 3)) return 'strong';
  if (password.length >= 12 || classes >= 3) return 'good';
  return 'fair';
}
