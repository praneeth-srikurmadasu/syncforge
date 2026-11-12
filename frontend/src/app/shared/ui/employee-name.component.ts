import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EmployeeNamesService } from '../../core/org/employee-names.service';
import { OrgContextService } from '../../core/org/org-context.service';

/** An employee referenced by ID, shown by name and linked to their page. */
@Component({
  selector: 'sf-employee-name',
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @switch (entry().state) {
      @case ('ok') {
        @if (link()) {
          <a
            [routerLink]="['/o', org.orgId(), 'employees', id()]"
            (click)="$event.stopPropagation()"
            >{{ entry().name }}</a
          >
        } @else {
          {{ entry().name }}
        }
      }
      @case ('loading') {
        <span class="sf-faint">…</span>
      }
      @case ('missing') {
        <span class="sf-faint" [attr.title]="id()">Removed employee</span>
      }
      @default {
        <code class="sf-faint" [attr.title]="'Name could not be loaded: ' + id()">{{
          id().slice(0, 8)
        }}</code>
      }
    }
  `,
})
export class EmployeeNameComponent {
  private readonly names = inject(EmployeeNamesService);
  protected readonly org = inject(OrgContextService);
  readonly id = input.required<string>();
  readonly link = input(false);
  protected readonly entry = computed(() => this.names.get(this.org.orgId(), this.id())());
}
