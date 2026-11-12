import { AbstractControl, FormGroup } from '@angular/forms';
import { ApiError } from '../core/api/api-error';

/**
 * Puts the API's 422 field messages on the matching form controls. Returns the issues
 * that matched no control, so the form can show them as a general error.
 */
export function applyServerErrors(form: FormGroup, error: ApiError): string[] {
  const unmatched: string[] = [];
  for (const issue of error.fieldIssues) {
    const control = form.get(issue.field);
    if (control) {
      control.setErrors({ ...(control.errors ?? {}), server: issue.message });
      control.markAsTouched();
    } else {
      unmatched.push(issue.field ? `${issue.field}: ${issue.message}` : issue.message);
    }
  }
  return unmatched;
}

/** The first validation message for a control, in plain language. */
export function controlError(control: AbstractControl | null, label = 'This field'): string | null {
  if (!control || !control.errors || !(control.touched || control.dirty)) return null;
  const e = control.errors;
  if (e['required']) return `${label} is required.`;
  if (e['email']) return 'Enter a valid email address.';
  if (e['minlength']) return `${label} needs at least ${e['minlength'].requiredLength} characters.`;
  if (e['maxlength'])
    return `${label} can have at most ${e['maxlength'].requiredLength} characters.`;
  if (e['pattern']) return `${label} has an invalid format.`;
  if (e['mismatch']) return 'The passwords do not match.';
  if (e['server']) return String(e['server']);
  return `${label} is invalid.`;
}

/** Only same-application paths are accepted as a post-login destination. */
export function safeReturnUrl(value: string | null | undefined): string | null {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) {
    return null;
  }
  return value.startsWith('/login') || value.startsWith('/register') ? null : value;
}
