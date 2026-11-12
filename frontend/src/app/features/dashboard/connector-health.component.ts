import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { OrgContextService } from '../../core/org/org-context.service';
import { Connector } from '../../core/api/models';
import { ApiError } from '../../core/api/api-error';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

@Component({
  selector: 'sf-connector-health',
  imports: [
    RouterLink,
    StatusBadgeComponent,
    BadgeComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-card__header"><h2 class="sf-card__title">Connector health</h2></div>
    @if (error(); as err) {
      <sf-error-state [error]="err" />
    } @else if (connectors(); as list) {
      @if (list.length === 0) {
        <sf-empty-state
          icon="plug"
          title="No connectors yet"
          message="Connect Slack, Google Workspace or payroll to start synchronizing."
        />
      } @else {
        <div class="sf-table-wrap">
          <table class="sf-table">
            <thead>
              <tr>
                <th scope="col">Connector</th>
                <th scope="col">Status</th>
                <th scope="col">Circuit</th>
                <th scope="col">Last test</th>
              </tr>
            </thead>
            <tbody>
              @for (c of list; track c.id) {
                <tr>
                  <td>
                    <div class="name">
                      <a
                        class="sf-cell-primary"
                        [routerLink]="['/o', orgId(), 'connectors', c.id]"
                        >{{ c.name }}</a
                      >
                      @if (c.simulated) {
                        <sf-badge
                          tone="info"
                          title="Talks to a local mock service, not the real product"
                          >Simulated</sf-badge
                        >
                      }
                    </div>
                    <span class="sf-faint type">{{ c.connector_type }} v{{ c.version }}</span>
                  </td>
                  <td><sf-status [value]="c.status" /></td>
                  <td>
                    <sf-status [value]="c.circuit.state" />
                    @if (c.circuit.consecutive_failures > 0) {
                      <span class="sf-faint fails"
                        >{{ c.circuit.consecutive_failures }} failures</span
                      >
                    }
                  </td>
                  <td><sf-time [value]="c.last_tested_at" /></td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    } @else if (loading()) {
      <sf-skeleton [rows]="4" />
    }
  `,
  styles: `
    :host {
      display: block;
      border: 1px solid var(--sf-border);
      border-radius: var(--sf-radius-lg);
      background: var(--sf-surface);
      overflow: hidden;
    }
    .name {
      display: flex;
      align-items: center;
      gap: var(--sf-space-2);
    }
    .type,
    .fails {
      display: block;
      font-size: var(--sf-text-xs);
    }
  `,
})
export class ConnectorHealthComponent {
  protected readonly orgId = inject(OrgContextService).orgId;
  readonly connectors = input<Connector[] | null>(null);
  readonly error = input<ApiError | null>(null);
  readonly loading = input(false);
}
