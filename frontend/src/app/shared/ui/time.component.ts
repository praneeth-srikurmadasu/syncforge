import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { formatDateTime, formatRelative } from '../../core/util/format';

/** A timestamp shown relative ("5 minutes ago") with the exact time on hover. */
@Component({
  selector: 'sf-time',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `@if (value()) {
      <time [attr.datetime]="value()" [attr.title]="absolute()">{{ text() }}</time>
    } @else {
      <span class="sf-faint">-</span>
    }`,
  styles: `
    :host {
      white-space: nowrap;
    }
  `,
})
export class TimeComponent {
  readonly value = input<string | null | undefined>();
  readonly absoluteOnly = input(false);
  protected readonly absolute = computed(() => formatDateTime(this.value()));
  protected readonly text = computed(() =>
    this.absoluteOnly() ? this.absolute() : formatRelative(this.value()),
  );
}
