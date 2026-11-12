import { formatDate, formatDuration, formatRelative, humanize, initials, todayIso } from './format';

describe('format helpers', () => {
  it('humanizes event types and enum values', () => {
    expect(humanize('employee.department_changed')).toBe('Department changed');
    expect(humanize('retries_exhausted')).toBe('Retries exhausted');
    expect(humanize(null)).toBe('-');
  });

  it('formats calendar dates without a timezone shift', () => {
    expect(formatDate('2026-01-01')).toContain('2026');
    expect(formatDate('2026-01-01')).toMatch(/1/);
  });

  it('formats durations', () => {
    expect(formatDuration(42.4)).toBe('42 ms');
    expect(formatDuration(1530)).toBe('1.53 s');
    expect(formatDuration(null)).toBe('-');
  });

  it('formats relative times', () => {
    const now = Date.parse('2026-05-01T12:00:00Z');
    expect(formatRelative('2026-05-01T11:55:00Z', now)).toMatch(/5 minutes ago/);
    expect(formatRelative('2026-05-01T09:00:00Z', now)).toMatch(/3 hours ago/);
  });

  it('builds initials and ISO dates', () => {
    expect(initials('Ada Lovelace King')).toBe('AK');
    expect(initials('Ada')).toBe('A');
    expect(todayIso(new Date(2026, 2, 9))).toBe('2026-03-09');
  });
});
