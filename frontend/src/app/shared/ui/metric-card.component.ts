import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Tone } from './badge.component';
import { IconComponent, IconName } from './icon.component';

/** One number from the API with its meaning. `value` null = not loaded / not available. */
@Component({
  selector: 'sf-metric',
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class]': '"tone-" + tone()' },
  template: `
    <div class="top">
      <span class="label">{{ label() }}</span>
      <sf-icon [name]="icon()" [size]="15" />
    </div>
    @if (error()) {
      <span class="value unavailable" title="Could not be loaded">-</span>
      <span class="hint err">Could not be loaded</span>
    } @else if (value() === null) {
      <span class="value loading" aria-label="Loading"></span>
      <span class="hint">&nbsp;</span>
    } @else {
      <span class="value sf-num">{{ value() }}</span>
      <span class="hint">
        @if (link()) {
          <a [routerLink]="link()">{{ hint() }}</a>
        } @else {
          {{ hint() }}
        }
      </span>
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: var(--sf-space-4);
      border: 1px solid var(--sf-border);
      border-radius: var(--sf-radius-lg);
      background: var(--sf-surface);
      min-width: 0;
    }
    .top {
      display: flex;
      justify-content: space-between;
      color: var(--sf-text-muted);
    }
    .label {
      font-size: var(--sf-text-sm);
    }
    .value {
      font-size: var(--sf-text-3xl);
      font-weight: 600;
      letter-spacing: -0.03em;
      line-height: 1.1;
    }
    .loading {
      display: block;
      width: 56px;
      height: 32px;
      border-radius: var(--sf-radius-sm);
      background: var(--sf-surface-hover);
    }
    .hint {
      font-size: var(--sf-text-xs);
      color: var(--sf-text-faint);
    }
    .err {
      color: var(--sf-danger);
    }
    :host(.tone-danger) .value {
      color: var(--sf-danger);
    }
    :host(.tone-warning) .value {
      color: var(--sf-warning);
    }
    :host(.tone-success) .value {
      color: var(--sf-success);
    }
  `,
})
export class MetricCardComponent {
  readonly label = input.required<string>();
  readonly value = input<number | string | null>(null);
  readonly hint = input('');
  readonly icon = input<IconName>('activity');
  readonly tone = input<Tone>('neutral');
  readonly link = input<unknown[] | string | null>(null);
  readonly error = input(false);
}
