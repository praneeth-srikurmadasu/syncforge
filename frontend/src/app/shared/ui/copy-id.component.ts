import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { ToastService } from '../../core/toast/toast.service';
import { IconComponent } from './icon.component';

/** A technical identifier in monospace, shortened, with a copy button. */
@Component({
  selector: 'sf-id',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <code [attr.title]="value()">{{ display() }}</code>
    <button type="button" class="copy" (click)="copy($event)" [attr.aria-label]="'Copy ' + value()">
      <sf-icon name="copy" [size]="12" />
    </button>
  `,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: 2px;
      color: var(--sf-text-muted);
      max-width: 100%;
    }
    code {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .copy {
      display: inline-grid;
      place-items: center;
      width: 20px;
      height: 20px;
      padding: 0;
      border: none;
      border-radius: var(--sf-radius-sm);
      background: transparent;
      color: var(--sf-text-faint);
      cursor: pointer;
    }
    .copy:hover {
      color: var(--sf-text);
      background: var(--sf-surface-hover);
    }
  `,
})
export class CopyIdComponent {
  private readonly toast = inject(ToastService);
  readonly value = input.required<string>();
  readonly short = input(true);
  protected readonly display = computed(() =>
    this.short() && this.value().length > 12 ? this.value().slice(0, 8) : this.value(),
  );

  protected async copy(event: Event): Promise<void> {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(this.value());
      this.toast.info('Copied to clipboard');
    } catch {
      this.toast.info('Copying is not available in this browser');
    }
  }
}
