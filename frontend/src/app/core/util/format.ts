// Display helpers shared by the screens. Pure functions: easy to test.

const dateTime = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});
const dateOnly = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
});
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTime.format(new Date(value)) : '-';
}

/** API dates (`YYYY-MM-DD`) are calendar dates: format them without a timezone shift. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '-';
  const [y, m, d] = value.slice(0, 10).split('-').map(Number);
  return dateOnly.format(new Date(y, m - 1, d));
}

export function formatRelative(value: string | null | undefined, now = Date.now()): string {
  if (!value) return '-';
  const seconds = Math.round((new Date(value).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return relative.format(seconds, 'second');
  if (abs < 2700) return relative.format(Math.round(seconds / 60), 'minute');
  if (abs < 79200) return relative.format(Math.round(seconds / 3600), 'hour');
  if (abs < 2592000) return relative.format(Math.round(seconds / 86400), 'day');
  return formatDate(value);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '-';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

/** `employee.department_changed` -> `Department changed`, `retries_exhausted` -> `Retries exhausted`. */
export function humanize(value: string | null | undefined): string {
  if (!value) return '-';
  const last = value.includes('.') ? value.slice(value.lastIndexOf('.') + 1) : value;
  const text = last.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : '-';
}

/** Today in the user's calendar as `YYYY-MM-DD`. */
export function todayIso(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function initials(name: string | null | undefined): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  return (
    (parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')
  ).toUpperCase();
}
