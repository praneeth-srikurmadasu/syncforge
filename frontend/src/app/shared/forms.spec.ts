import { FormControl, FormGroup, Validators } from '@angular/forms';
import { ApiError } from '../core/api/api-error';
import { applyServerErrors, controlError, safeReturnUrl } from './forms';

describe('form helpers', () => {
  it('accepts only same-application return URLs', () => {
    expect(safeReturnUrl('/o/1/employees?page=2')).toBe('/o/1/employees?page=2');
    expect(safeReturnUrl('https://evil.example')).toBeNull();
    expect(safeReturnUrl('//evil.example')).toBeNull();
    expect(safeReturnUrl('/\\evil.example')).toBeNull();
    expect(safeReturnUrl('/login')).toBeNull();
    expect(safeReturnUrl(null)).toBeNull();
  });

  it('puts API field errors on the matching controls', () => {
    const form = new FormGroup({ email: new FormControl(''), name: new FormControl('') });
    const error = new ApiError(
      422,
      'validation_error',
      'Request validation failed.',
      [
        { field: 'email', message: 'already used' },
        { field: 'other', message: 'unknown field' },
      ],
      null,
    );
    const unmatched = applyServerErrors(form, error);
    expect(form.controls.email.errors?.['server']).toBe('already used');
    expect(controlError(form.controls.email, 'Email')).toBe('already used');
    expect(unmatched).toEqual(['other: unknown field']);
  });

  it('only reports errors on touched controls', () => {
    const control = new FormControl('', Validators.required);
    expect(controlError(control, 'Name')).toBeNull();
    control.markAsTouched();
    expect(controlError(control, 'Name')).toBe('Name is required.');
  });
});
