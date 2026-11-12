import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';

export interface TabItem {
  id: string;
  label: string;
  count?: number | null;
}

/** Tab bar (ARIA tabs pattern). The parent renders the panel for `active()`. */
@Component({
  selector: 'sf-tabs',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="bar" role="tablist">
      @for (tab of tabs(); track tab.id) {
        <button
          type="button"
          role="tab"
          [id]="'tab-' + tab.id"
          [attr.aria-selected]="tab.id === active()"
          [attr.tabindex]="tab.id === active() ? 0 : -1"
          [class.active]="tab.id === active()"
          (click)="active.set(tab.id)"
          (keydown)="onKey($event)"
        >
          {{ tab.label }}
          @if (tab.count !== undefined && tab.count !== null) {
            <span class="count sf-num">{{ tab.count }}</span>
          }
        </button>
      }
    </div>
  `,
  styles: `
    .bar {
      display: flex;
      gap: var(--sf-space-1);
      border-bottom: 1px solid var(--sf-border);
      overflow-x: auto;
    }
    button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 10px 12px;
      border: none;
      border-bottom: 2px solid transparent;
      background: none;
      color: var(--sf-text-muted);
      font: inherit;
      font-size: var(--sf-text-sm);
      font-weight: 500;
      white-space: nowrap;
      cursor: pointer;
      margin-bottom: -1px;
    }
    button:hover {
      color: var(--sf-text);
    }
    button.active {
      color: var(--sf-text);
      border-bottom-color: var(--sf-accent);
    }
    .count {
      padding: 0 6px;
      border-radius: var(--sf-radius-pill);
      background: var(--sf-neutral-soft);
      font-size: var(--sf-text-xs);
    }
  `,
})
export class TabsComponent {
  readonly tabs = input.required<TabItem[]>();
  readonly active = model.required<string>();

  protected onKey(event: KeyboardEvent): void {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    const tabs = this.tabs();
    const index = tabs.findIndex((t) => t.id === this.active());
    const next = (index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
    this.active.set(tabs[next].id);
    document.getElementById('tab-' + tabs[next].id)?.focus();
  }
}
