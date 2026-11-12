import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { PasswordFieldComponent, passwordStrength } from './password-field.component';

@Component({
  imports: [PasswordFieldComponent],
  template: `<sf-password-field><input id="pw" type="password" /></sf-password-field>`,
})
class Host {}

describe('PasswordFieldComponent', () => {
  it('shows and hides the password with an accessible toggle', async () => {
    const fixture = TestBed.createComponent(Host);
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector<HTMLInputElement>('#pw')!;
    const button = el.querySelector<HTMLButtonElement>('button.toggle')!;
    expect(button.type).toBe('button'); // never submits the form
    expect(button.getAttribute('aria-label')).toBe('Show password');

    button.click();
    await fixture.whenStable();
    expect(input.type).toBe('text');
    expect(button.getAttribute('aria-label')).toBe('Hide password');
    expect(button.getAttribute('aria-pressed')).toBe('true');

    button.click();
    await fixture.whenStable();
    expect(input.type).toBe('password');
  });
});

describe('passwordStrength', () => {
  it('rates length first', () => {
    expect(passwordStrength('short')).toBe('weak');
    expect(passwordStrength('eightchr')).toBe('fair');
    expect(passwordStrength('twelve chars')).toBe('good');
    expect(passwordStrength('Twelve-Chars1')).toBe('strong');
    expect(passwordStrength('a long simple passphrase')).toBe('strong');
  });
});
