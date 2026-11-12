import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ToastService } from '../../core/toast/toast.service';
import { IconComponent } from './icon.component';

@Component({
  selector: 'sf-toast-outlet',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="stack" role="status" aria-live="polite">
      @for (toast of toasts.toasts(); track toast.id) {
        <div class="toast" [class]="'toast toast--' + toast.kind">
          <sf-icon
            [name]="
              toast.kind === 'success'
                ? 'circle-check'
                : toast.kind === 'error'
                  ? 'circle-alert'
                  : 'info'
            "
          />
          <div class="text">
            <span>{{ toast.message }}</span>
            @if (toast.requestId) {
              <code class="rid">Request {{ toast.requestId }}</code>
            }
          </div>
          <button type="button" aria-label="Dismiss" (click)="toasts.dismiss(toast.id)">
            <sf-icon name="x" [size]="14" />
          </button>
        </div>
      }
    </div>
  `,
  styles: `
    .stack {
      position: fixed;
      right: var(--sf-space-4);
      bottom: var(--sf-space-4);
      z-index: 2000;
      display: flex;
      flex-direction: column;
      gap: var(--sf-space-2);
      width: min(400px, calc(100vw - 32px));
    }
    .toast {
      display: flex;
      align-items: flex-start;
      gap: var(--sf-space-3);
      padding: var(--sf-space-3) var(--sf-space-4);
      border-radius: var(--sf-radius-md);
      background: var(--sf-surface-raised);
      box-shadow: var(--sf-shadow-overlay);
      font-size: var(--sf-text-sm);
      animation: rise 160ms var(--sf-ease);
    }
    .toast--success sf-icon {
      color: var(--sf-success);
    }
    .toast--error sf-icon {
      color: var(--sf-danger);
    }
    .toast--info sf-icon {
      color: var(--sf-info);
    }
    .text {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .rid {
      font-size: var(--sf-text-xs);
      color: var(--sf-text-faint);
      overflow-wrap: anywhere;
    }
    button {
      border: none;
      background: none;
      color: var(--sf-text-faint);
      cursor: pointer;
      padding: 2px;
    }
    @keyframes rise {
      from {
        transform: translateY(6px);
        opacity: 0;
      }
    }
  `,
})
export class ToastOutletComponent {
  protected readonly toasts = inject(ToastService);
}
