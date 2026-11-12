import { ConflictField } from '../../core/api/models';

/** The seven fields reconciliation compares (CONFLICT_FIELDS in the backend). */
export const CONFLICT_FIELDS: { value: ConflictField; label: string }[] = [
  { value: 'first_name', label: 'First name' },
  { value: 'last_name', label: 'Last name' },
  { value: 'email', label: 'Email' },
  { value: 'department', label: 'Department' },
  { value: 'designation', label: 'Designation' },
  { value: 'location', label: 'Location' },
  { value: 'account_active', label: 'Account active' },
];

export function fieldLabel(field: string): string {
  return CONFLICT_FIELDS.find((f) => f.value === field)?.label ?? field;
}
