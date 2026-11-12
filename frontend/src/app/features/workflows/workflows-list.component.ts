import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { WorkflowQuery, WorkflowsApi } from '../../core/api/integrations.api';
import { EVENT_TYPES, Page, Workflow } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { useQueryState } from '../../shared/query-state';
import { BadgeComponent } from '../../shared/ui/badge.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

@Component({
  selector: 'sf-workflows-list',
  imports: [
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    IconComponent,
    PaginationComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-page-header
        title="Workflows"
        description="Each workflow listens for one lifecycle event and runs its steps, in order, against your connectors."
      >
        @if (org.can('workflows:manage')) {
          <a class="sf-btn sf-btn--primary" [routerLink]="['/o', org.orgId(), 'workflows', 'new']">
            <sf-icon name="plus" [size]="14" /> New workflow
          </a>
        }
      </sf-page-header>

      <div class="sf-card">
        <div class="sf-filters">
          <div class="sf-field">
            <label for="wf-trigger">Trigger</label>
            <select
              id="wf-trigger"
              class="sf-select"
              (change)="q.set({ trigger: $any($event.target).value })"
            >
              <option value="">Any trigger</option>
              @for (t of triggers; track t) {
                <option [value]="t" [selected]="q.get('trigger') === t">{{ t }}</option>
              }
            </select>
          </div>
          <div class="sf-field">
            <label for="wf-active">State</label>
            <select
              id="wf-active"
              class="sf-select"
              (change)="q.set({ active: $any($event.target).value })"
            >
              <option value="">Active and inactive</option>
              <option value="true" [selected]="q.get('active') === 'true'">Active</option>
              <option value="false" [selected]="q.get('active') === 'false'">Inactive</option>
            </select>
          </div>
        </div>

        @if (workflows.error(); as err) {
          <sf-error-state [error]="err" (retry)="workflows.reload()" />
        } @else if (workflows.hasValue()) {
          @let page = workflows.value();
          @if (page.items.length === 0) {
            <sf-empty-state
              icon="workflow"
              title="No workflows"
              message="Create one to provision accounts when people join, change roles or leave."
            >
              @if (org.can('workflows:manage')) {
                <a
                  class="sf-btn sf-btn--primary"
                  [routerLink]="['/o', org.orgId(), 'workflows', 'new']"
                  >New workflow</a
                >
              }
            </sf-empty-state>
          } @else {
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Trigger</th>
                  <th scope="col">Steps</th>
                  <th scope="col">State</th>
                  <th scope="col" class="sf-cell-num">Version</th>
                  <th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                @for (w of page.items; track w.id) {
                  <tr class="sf-row-link" (click)="open(w)">
                    <td>
                      <a
                        class="sf-cell-primary"
                        [routerLink]="['/o', org.orgId(), 'workflows', w.id]"
                        (click)="$event.stopPropagation()"
                        >{{ w.name }}</a
                      >
                      @if (w.description) {
                        <span class="sf-faint desc">{{ w.description }}</span>
                      }
                    </td>
                    <td>
                      <code>{{ w.trigger_event_type }}</code>
                    </td>
                    <td class="steps">
                      @for (s of w.steps; track s.position) {
                        <span class="sf-muted"
                          >{{ s.connector_name
                          }}<code class="sf-faint">.{{ s.operation }}</code></span
                        >
                      }
                    </td>
                    <td>
                      <sf-badge [tone]="w.is_active ? 'success' : 'neutral'" [dot]="true">{{
                        w.is_active ? 'Active' : 'Inactive'
                      }}</sf-badge>
                    </td>
                    <td class="sf-cell-num">{{ w.version }}</td>
                    <td><sf-time [value]="w.updated_at" /></td>
                  </tr>
                }
              </tbody>
            </table>
            <sf-pagination
              [total]="page.total"
              [limit]="page.limit"
              [offset]="page.offset"
              (offsetChange)="q.set({ offset: $event || null }, false)"
            />
          }
        } @else {
          <sf-skeleton [rows]="5" />
        }
      </div>
    </div>
  `,
  styles: `
    .desc {
      display: block;
      font-size: var(--sf-text-xs);
    }
    .steps {
      display: flex;
      flex-direction: column;
      font-size: var(--sf-text-xs);
    }
  `,
})
export class WorkflowsListComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(WorkflowsApi);
  private readonly router = inject(Router);
  protected readonly q = useQueryState();
  protected readonly triggers = EVENT_TYPES;

  private readonly query = computed<WorkflowQuery>(() => {
    this.q.params();
    const active = this.q.get('active');
    return {
      trigger_event_type: this.q.get('trigger') || undefined,
      is_active: active === '' ? undefined : active === 'true',
      limit: 25,
      offset: this.q.number('offset'),
    };
  });
  protected readonly workflows = httpResource<Page<Workflow>>(() =>
    this.api.listRequest(this.org.orgId(), this.query()),
  );

  protected open(w: Workflow): void {
    void this.router.navigate(['/o', this.org.orgId(), 'workflows', w.id]);
  }
}
