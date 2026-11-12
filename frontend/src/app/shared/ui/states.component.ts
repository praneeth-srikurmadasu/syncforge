import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { ApiError } from '../../core/api/api-error';
import { IconComponent, IconName } from './icon.component';
import { CopyIdComponent } from './copy-id.component';

/** An empty list or screen: says what is missing and, through projected content, what to do. */
@Component({
  selector: 'sf-empty-state',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="icon"><sf-icon [name]="icon()" [size]="20" /></div>
    <h3>{{ title() }}</h3>
    @if (message()) {
      <p class="sf-muted">{{ message() }}</p>
    }
    <div class="action"><ng-content /></div>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--sf-space-2);
      padding: var(--sf-space-7) var(--sf-space-4);
      text-align: center;
    }
    .icon {
      display: grid;
      place-items: center;
      width: 40px;
      height: 40px;
      border-radius: var(--sf-radius-md);
      background: var(--sf-neutral-soft);
      color: var(--sf-text-muted);
    }
    p {
      max-width: 48ch;
      font-size: var(--sf-text-sm);
    }
    .action:not(:empty) {
      margin-top: var(--sf-space-2);
    }
  `,
})
export class EmptyStateComponent {
  readonly icon = input<IconName>('inbox');
  readonly title = input.required<string>();
  readonly message = input<string>();
}

/**
 * A failed request: the API's message, what it means, the request ID for tracing in the
 * backend logs, and a retry action.
 */
@Component({
  selector: 'sf-error-state',
  imports: [IconComponent, CopyIdComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="icon"><sf-icon [name]="icon()" [size]="20" /></div>
    <h3>{{ heading() }}</h3>
    <p class="sf-muted">{{ apiError().message }}</p>
    @if (apiError().requestId) {
      <p class="rid sf-faint">
        Request ID <sf-id [value]="apiError().requestId!" [short]="false" />
      </p>
    }
    @if (retryable()) {
      <button type="button" class="sf-btn" (click)="retry.emit()">
        <sf-icon name="refresh" [size]="14" /> Try again
      </button>
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--sf-space-2);
      padding: var(--sf-space-6) var(--sf-space-4);
      text-align: center;
    }
    .icon {
      display: grid;
      place-items: center;
      width: 40px;
      height: 40px;
      border-radius: var(--sf-radius-md);
      background: var(--sf-danger-soft);
      color: var(--sf-danger);
    }
    p {
      max-width: 60ch;
      font-size: var(--sf-text-sm);
    }
    .rid {
      font-size: var(--sf-text-xs);
    }
  `,
})
export class ErrorStateComponent {
  readonly error = input.required<unknown>();
  readonly retry = output<void>();

  protected readonly apiError = computed(() => ApiError.from(this.error()));
  protected readonly retryable = computed(() => ![403, 404].includes(this.apiError().status));
  protected readonly icon = computed<IconName>(() =>
    this.apiError().status === 403 ? 'shield-alert' : 'circle-alert',
  );
  protected readonly heading = computed(() => {
    const e = this.apiError();
    if (e.isNetwork) return 'API unreachable';
    if (e.status === 403) return 'Not permitted';
    if (e.status === 404) return 'Not found';
    if (e.status >= 500) return 'The server could not complete the request';
    return 'The request failed';
  });
}

@Component({
  selector: 'sf-skeleton',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { 'aria-busy': 'true', 'aria-label': 'Loading' },
  template: `
    @for (row of rowsArray(); track $index) {
      <div
        class="line"
        [style.height.px]="height()"
        [style.width]="$index % 3 === 2 ? '70%' : '100%'"
      ></div>
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: var(--sf-space-4);
    }
    .line {
      border-radius: var(--sf-radius-sm);
      background: linear-gradient(
        90deg,
        var(--sf-surface-hover) 0%,
        var(--sf-surface-raised) 50%,
        var(--sf-surface-hover) 100%
      );
      background-size: 200% 100%;
      animation: shimmer 1.4s linear infinite;
    }
    @keyframes shimmer {
      to {
        background-position: -200% 0;
      }
    }
  `,
})
export class SkeletonComponent {
  readonly rows = input(4);
  readonly height = input(14);
  protected readonly rowsArray = computed(() => Array.from({ length: this.rows() }));
}
