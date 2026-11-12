import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IconComponent } from './icon.component';

export interface Crumb {
  label: string;
  link?: unknown[] | string;
}

@Component({
  selector: 'sf-page-header',
  imports: [RouterLink, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (crumbs().length) {
      <nav class="crumbs" aria-label="Breadcrumb">
        <ol>
          @for (crumb of crumbs(); track $index; let last = $last) {
            <li>
              @if (crumb.link && !last) {
                <a [routerLink]="crumb.link">{{ crumb.label }}</a>
                <sf-icon name="chevron-right" [size]="12" />
              } @else {
                <span [attr.aria-current]="last ? 'page' : null">{{ crumb.label }}</span>
              }
            </li>
          }
        </ol>
      </nav>
    }
    <div class="row">
      <div class="titles">
        <h1>{{ title() }}</h1>
        @if (description()) {
          <p class="sf-muted">{{ description() }}</p>
        }
        <ng-content select="[meta]" />
      </div>
      <div class="actions"><ng-content /></div>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .crumbs ol {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin: 0 0 var(--sf-space-2);
      padding: 0;
      list-style: none;
      font-size: var(--sf-text-sm);
      color: var(--sf-text-muted);
    }
    .crumbs li {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .crumbs a {
      color: var(--sf-text-muted);
    }
    .row {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: var(--sf-space-4);
      flex-wrap: wrap;
    }
    .titles {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }
    .titles p {
      max-width: 72ch;
    }
    .actions {
      display: flex;
      gap: var(--sf-space-2);
      flex-wrap: wrap;
    }
  `,
})
export class PageHeaderComponent {
  readonly title = input.required<string>();
  readonly description = input<string>();
  readonly crumbs = input<Crumb[]>([]);
}
