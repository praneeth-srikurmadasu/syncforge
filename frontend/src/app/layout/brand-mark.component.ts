import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** SyncForge mark: two offset arcs meeting at a shared node - records kept in step. */
@Component({
  selector: 'sf-brand-mark',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { 'aria-hidden': 'true' },
  template: `
    <svg [attr.width]="size()" [attr.height]="size()" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="var(--sf-accent)" />
      <path d="M9 19a7 7 0 0 1 11.5-8.4" stroke="#fff" stroke-width="2.6" stroke-linecap="round" />
      <path
        d="M23 13a7 7 0 0 1-11.5 8.4"
        stroke="#fff"
        stroke-opacity="0.62"
        stroke-width="2.6"
        stroke-linecap="round"
      />
      <circle cx="16" cy="16" r="2.2" fill="#fff" />
    </svg>
  `,
  styles: `
    :host {
      display: inline-flex;
      line-height: 0;
    }
  `,
})
export class BrandMarkComponent {
  readonly size = input(26);
}
