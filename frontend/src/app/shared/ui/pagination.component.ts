import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { IconComponent } from './icon.component';

@Component({
  selector: 'sf-pagination',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="sf-muted sf-num">
      @if (total() === 0) {
        No results
      } @else {
        {{ from() }}-{{ to() }} of {{ total() }}
      }
    </span>
    <div class="buttons">
      <button
        type="button"
        class="sf-btn sf-btn--sm"
        [disabled]="offset() === 0"
        (click)="offsetChange.emit(prevOffset())"
      >
        <sf-icon name="chevron-left" [size]="14" /> Previous
      </button>
      <button
        type="button"
        class="sf-btn sf-btn--sm"
        [disabled]="to() >= total()"
        (click)="offsetChange.emit(offset() + limit())"
      >
        Next <sf-icon name="chevron-right" [size]="14" />
      </button>
    </div>
  `,
  styles: `
    :host {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--sf-space-3);
      padding: var(--sf-space-3) var(--sf-space-4);
      border-top: 1px solid var(--sf-border);
      font-size: var(--sf-text-sm);
    }
    .buttons {
      display: flex;
      gap: var(--sf-space-2);
    }
  `,
})
export class PaginationComponent {
  readonly total = input.required<number>();
  readonly limit = input.required<number>();
  readonly offset = input.required<number>();
  readonly offsetChange = output<number>();

  protected readonly from = computed(() => Math.min(this.offset() + 1, this.total()));
  protected readonly to = computed(() => Math.min(this.offset() + this.limit(), this.total()));
  protected readonly prevOffset = computed(() => Math.max(0, this.offset() - this.limit()));
}
