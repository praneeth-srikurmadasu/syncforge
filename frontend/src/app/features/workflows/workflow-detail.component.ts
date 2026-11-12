import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { WorkflowsApi } from '../../core/api/integrations.api';
import { Execution, ExecutionStatus, Page, Workflow } from '../../core/api/models';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { humanize } from '../../core/util/format';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { DialogService } from '../../shared/ui/dialog';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { PaginationComponent } from '../../shared/ui/pagination.component';
import {
  EmptyStateComponent,
  ErrorStateComponent,
  SkeletonComponent,
} from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';
import { WorkflowStepsComponent } from './workflow-steps.component';

@Component({
  selector: 'sf-workflow-detail',
  imports: [
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    EmployeeNameComponent,
    IconComponent,
    PaginationComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
    WorkflowStepsComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      @if (workflow.error(); as err) {
        <sf-page-header
          title="Workflow"
          [crumbs]="[
            { label: 'Workflows', link: ['/o', org.orgId(), 'workflows'] },
            { label: 'Workflow' },
          ]"
        />
        <div class="sf-card"><sf-error-state [error]="err" (retry)="workflow.reload()" /></div>
      } @else if (workflow.hasValue()) {
        @let w = workflow.value();
        <sf-page-header
          [title]="w.name"
          [description]="w.description ?? undefined"
          [crumbs]="[
            { label: 'Workflows', link: ['/o', org.orgId(), 'workflows'] },
            { label: w.name },
          ]"
        >
          <div meta class="meta">
            <sf-badge [tone]="w.is_active ? 'success' : 'neutral'" [dot]="true">{{
              w.is_active ? 'Active' : 'Inactive'
            }}</sf-badge>
            <span class="sf-muted"
              >Version {{ w.version }}, updated <sf-time [value]="w.updated_at"
            /></span>
          </div>
          @if (org.can('workflows:manage')) {
            <a class="sf-btn" [routerLink]="['/o', org.orgId(), 'workflows', w.id, 'edit']">
              <sf-icon name="pencil" [size]="14" /> Edit
            </a>
            <button
              type="button"
              class="sf-btn"
              [class.sf-btn--primary]="!w.is_active"
              [disabled]="busy()"
              (click)="toggle(w)"
            >
              <sf-icon [name]="w.is_active ? 'power' : 'play'" [size]="14" />
              {{ w.is_active ? 'Deactivate' : 'Activate' }}
            </button>
          }
        </sf-page-header>

        @if (!w.is_active) {
          <div class="sf-alert sf-alert--info" role="status">
            Inactive: new <code>{{ w.trigger_event_type }}</code> events do not run this workflow.
          </div>
        }

        <section class="sf-card sf-card__body">
          <sf-workflow-steps
            [trigger]="w.trigger_event_type"
            [steps]="w.steps"
            [orgId]="org.orgId()"
          />
        </section>

        <section class="sf-card">
          <div class="sf-card__header">
            <h2 class="sf-card__title">Executions</h2>
            <div class="sf-field status-filter">
              <label for="ex-status" class="sf-visually-hidden">Execution status</label>
              <select
                id="ex-status"
                class="sf-select"
                (change)="setStatus($any($event.target).value)"
              >
                <option value="">Any result</option>
                <option value="running">Running</option>
                <option value="succeeded">Succeeded</option>
                <option value="failed">Failed</option>
              </select>
            </div>
          </div>
          @if (executions.error(); as err) {
            <sf-error-state [error]="err" (retry)="executions.reload()" />
          } @else if (executions.value(); as page) {
            @if (page.items.length === 0) {
              <sf-empty-state
                icon="workflow"
                title="No executions"
                message="Executions appear when a matching event is processed while the workflow is active."
              />
            } @else {
              <div class="sf-table-wrap">
                <table class="sf-table">
                  <thead>
                    <tr>
                      <th scope="col">Event</th>
                      <th scope="col">Employee</th>
                      <th scope="col">Result</th>
                      <th scope="col">Steps</th>
                      <th scope="col" class="sf-cell-num">Version</th>
                      <th scope="col">Started</th>
                      <th scope="col">Finished</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (x of page.items; track x.id) {
                      <tr>
                        <td>
                          <a [routerLink]="['/o', org.orgId(), 'events', x.event_id]">{{
                            humanize(x.event_type)
                          }}</a>
                        </td>
                        <td><sf-employee-name [id]="x.employee_id" /></td>
                        <td><sf-status [value]="x.status" /></td>
                        <td class="jobs">
                          @for (j of x.jobs; track j.position) {
                            <span
                              class="job"
                              [attr.title]="j.operation + ': ' + j.status"
                              [class]="'job job--' + j.status"
                              >{{ j.position }}</span
                            >
                          }
                        </td>
                        <td class="sf-cell-num">{{ x.workflow_version }}</td>
                        <td><sf-time [value]="x.started_at" /></td>
                        <td><sf-time [value]="x.finished_at" /></td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
              <sf-pagination
                [total]="page.total"
                [limit]="page.limit"
                [offset]="page.offset"
                (offsetChange)="offset.set($event)"
              />
            }
          } @else {
            <sf-skeleton [rows]="5" />
          }
        </section>
      } @else {
        <sf-skeleton [rows]="8" />
      }
    </div>
  `,
  styles: `
    .meta {
      display: flex;
      align-items: center;
      gap: var(--sf-space-3);
      margin-top: 4px;
      font-size: var(--sf-text-sm);
    }
    .status-filter {
      width: 160px;
    }
    .jobs {
      display: flex;
      gap: 4px;
    }
    .job {
      display: grid;
      place-items: center;
      width: 22px;
      height: 22px;
      border-radius: var(--sf-radius-sm);
      background: var(--sf-neutral-soft);
      color: var(--sf-text-muted);
      font-size: var(--sf-text-xs);
      font-weight: 600;
    }
    .job--succeeded {
      background: var(--sf-success-soft);
      color: var(--sf-success);
    }
    .job--failed {
      background: var(--sf-danger-soft);
      color: var(--sf-danger);
    }
    .job--retrying,
    .job--running {
      background: var(--sf-warning-soft);
      color: var(--sf-warning);
    }
  `,
})
export class WorkflowDetailComponent {
  readonly id = input.required<string>();

  protected readonly org = inject(OrgContextService);
  private readonly api = inject(WorkflowsApi);
  private readonly toast = inject(ToastService);
  private readonly dialogs = inject(DialogService);
  protected readonly humanize = humanize;

  protected readonly status = signal<ExecutionStatus | ''>('');
  protected readonly offset = signal(0);
  protected readonly busy = signal(false);

  protected readonly workflow = httpResource<Workflow>(() =>
    this.api.getRequest(this.org.orgId(), this.id()),
  );
  private readonly query = computed(() => ({
    execution_status: this.status(),
    limit: 20,
    offset: this.offset(),
  }));
  protected readonly executions = httpResource<Page<Execution>>(() =>
    this.api.executionsRequest(this.org.orgId(), this.id(), this.query()),
  );

  protected setStatus(value: string): void {
    this.status.set(value as ExecutionStatus | '');
    this.offset.set(0);
  }

  protected async toggle(w: Workflow): Promise<void> {
    const activate = !w.is_active;
    if (!activate) {
      const ok = await this.dialogs.confirm({
        title: `Deactivate ${w.name}?`,
        message: `${w.trigger_event_type} events processed from now on will not run this workflow until it is activated again.`,
        confirmLabel: 'Deactivate',
        tone: 'danger',
      });
      if (!ok) return;
    }
    this.busy.set(true);
    this.api.setActive(this.org.orgId(), w.id, activate).subscribe({
      next: (updated) => {
        this.busy.set(false);
        this.workflow.set(updated);
        this.toast.success(activate ? `${w.name} is active` : `${w.name} deactivated`);
      },
      error: (e: unknown) => {
        this.busy.set(false);
        const err = ApiError.from(e);
        const names = (err.details as { connectors?: string[] } | null)?.connectors;
        this.toast.error(
          err,
          names?.length
            ? `Activation refused (${names.join(', ')})`
            : activate
              ? 'Activation refused'
              : 'Deactivation failed',
        );
      },
    });
  }
}
