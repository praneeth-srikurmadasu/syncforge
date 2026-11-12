import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { humanize } from '../../core/util/format';

export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

@Component({
  selector: 'sf-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class]': '"sf-badge sf-badge--" + tone()' },
  template: `@if (dot()) {
      <span class="dot"></span>
    }
    <ng-content />`,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 22px;
      padding: 0 8px;
      border-radius: var(--sf-radius-pill);
      font-size: var(--sf-text-xs);
      font-weight: 500;
      white-space: nowrap;
      background: var(--sf-neutral-soft);
      color: var(--sf-text-muted);
    }
    .dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
    }
    :host(.sf-badge--accent) {
      background: var(--sf-accent-soft);
      color: var(--sf-accent-text);
    }
    :host(.sf-badge--success) {
      background: var(--sf-success-soft);
      color: var(--sf-success);
    }
    :host(.sf-badge--warning) {
      background: var(--sf-warning-soft);
      color: var(--sf-warning);
    }
    :host(.sf-badge--danger) {
      background: var(--sf-danger-soft);
      color: var(--sf-danger);
    }
    :host(.sf-badge--info) {
      background: var(--sf-info-soft);
      color: var(--sf-info);
    }
  `,
})
export class BadgeComponent {
  readonly tone = input<Tone>('neutral');
  readonly dot = input(false);
}

/** Every status value the API returns, mapped to one tone. */
const STATUS_TONES: Record<string, Tone> = {
  // employees
  active: 'success',
  on_leave: 'warning',
  terminated: 'neutral',
  archived: 'neutral',
  // connectors
  connected: 'success',
  pending: 'neutral',
  error: 'danger',
  disconnected: 'neutral',
  // circuit
  closed: 'success',
  open: 'danger',
  half_open: 'warning',
  // events, jobs, executions, attempts
  processing: 'info',
  running: 'info',
  retrying: 'warning',
  completed: 'success',
  succeeded: 'success',
  failed: 'danger',
  skipped: 'neutral',
  interrupted: 'warning',
  dead_letter: 'danger',
  // dead letters, conflicts
  replayed: 'success',
  resolved: 'success',
  dismissed: 'neutral',
  // audit
  success: 'success',
  failure: 'danger',
  // severity
  low: 'neutral',
  medium: 'info',
  high: 'warning',
  critical: 'danger',
  deactivated: 'neutral',
};

const STATUS_LABELS: Record<string, string> = {
  dead_letter: 'Dead letter',
  half_open: 'Half-open',
  on_leave: 'On leave',
};

/** A status value from the API rendered with a consistent tone and label. */
@Component({
  selector: 'sf-status',
  imports: [BadgeComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<sf-badge [tone]="tone()" [dot]="true">{{ label() || text() }}</sf-badge>`,
})
export class StatusBadgeComponent {
  readonly value = input.required<string | null | undefined>();
  readonly label = input<string>();
  protected readonly tone = computed(() => STATUS_TONES[this.value() ?? ''] ?? 'neutral');
  protected readonly text = computed(() => {
    const v = this.value() ?? '';
    return STATUS_LABELS[v] ?? humanize(v);
  });
}

export function statusTone(value: string): Tone {
  return STATUS_TONES[value] ?? 'neutral';
}
