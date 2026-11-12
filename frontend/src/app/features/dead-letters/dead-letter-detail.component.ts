import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiError } from '../../core/api/api-error';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { Connector, DeadLetterDetail, Page } from '../../core/api/models';
import { DeadLettersApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { humanize } from '../../core/util/format';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { CopyIdComponent } from '../../shared/ui/copy-id.component';
import { DialogService } from '../../shared/ui/dialog';
import { EmployeeNameComponent } from '../../shared/ui/employee-name.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { ErrorStateComponent, SkeletonComponent } from '../../shared/ui/states.component';
import { TimeComponent } from '../../shared/ui/time.component';

const REASONS: Record<string, string> = {
  retries_exhausted: 'The step kept failing with temporary errors until its retry budget ran out.',
  non_retryable:
    'The application answered with an error that retrying cannot fix (for example invalid credentials or rejected data).',
};

@Component({
  selector: 'sf-dead-letter-detail',
  imports: [
    RouterLink,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    CopyIdComponent,
    EmployeeNameComponent,
    IconComponent,
    ErrorStateComponent,
    SkeletonComponent,
    TimeComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      @if (entry.error(); as err) {
        <sf-page-header title="Dead letter" [crumbs]="crumbs()" />
        <div class="sf-card"><sf-error-state [error]="err" (retry)="entry.reload()" /></div>
      } @else if (entry.hasValue()) {
        @let d = entry.value();
        <sf-page-header [title]="'Dead letter: ' + d.event_type" [crumbs]="crumbs()">
          <div meta class="meta">
            <sf-status [value]="d.status" />
            <span class="sf-muted">for <sf-employee-name [id]="d.employee_id" /></span>
          </div>
          @if (org.can('events:replay') && d.status === 'open') {
            <button
              type="button"
              class="sf-btn sf-btn--primary"
              [disabled]="busy()"
              (click)="replay(d)"
            >
              <sf-icon name="replay" [size]="14" /> {{ busy() ? 'Replaying…' : 'Replay' }}
            </button>
          }
        </sf-page-header>

        @if (replayError(); as err) {
          <div class="sf-alert sf-alert--danger" role="alert">
            <span>
              <strong>Replay refused:</strong> {{ err.message }}
              @if (err.code === 'workflow_inactive') {
                <a [routerLink]="['/o', org.orgId(), 'workflows']">Open workflows</a>
              }
            </span>
          </div>
        }
        @if (d.status === 'replayed') {
          <div class="sf-alert sf-alert--info" role="status">
            <sf-icon name="replay" />
            <span>
              Replayed <sf-time [value]="d.replayed_at" />: the failed steps were sent back for
              processing with a fresh retry budget; steps that had succeeded are not repeated.
              <a [routerLink]="['/o', org.orgId(), 'events', d.event_id]">Follow the event</a>.
            </span>
          </div>
        }

        <div class="sf-grid sf-grid--2">
          <section class="sf-card">
            <div class="sf-card__header"><h2 class="sf-card__title">What failed</h2></div>
            <div class="sf-card__body">
              <dl class="sf-dl">
                <dt>Reason</dt>
                <dd>
                  <sf-badge [tone]="d.reason === 'non_retryable' ? 'danger' : 'warning'">{{
                    humanize(d.reason)
                  }}</sf-badge>
                  <span class="explain">{{ reasons[d.reason] }}</span>
                </dd>
                <dt>Step</dt>
                <dd class="inline">
                  @if (d.connector_id) {
                    <a [routerLink]="['/o', org.orgId(), 'connectors', d.connector_id]">{{
                      connectorNames().get(d.connector_id) ?? 'Connector'
                    }}</a>
                  }
                  <code>{{ d.operation ?? '-' }}</code>
                </dd>
                <dt>Error</dt>
                <dd class="inline">
                  {{ humanize(d.error_category) }}
                  @if (d.error_code) {
                    <code class="sf-faint">{{ d.error_code }}</code>
                  }
                  @if (d.http_status) {
                    <code class="sf-faint">HTTP {{ d.http_status }}</code>
                  }
                  @if (d.error_message) {
                    <span class="explain">{{ d.error_message }}</span>
                  }
                </dd>
                <dt>Attempts</dt>
                <dd class="sf-num">{{ d.attempts }}</dd>
                <dt>Failed steps</dt>
                <dd class="sf-num">{{ d.failed_steps }}</dd>
                <dt>Dead-lettered</dt>
                <dd><sf-time [value]="d.dead_lettered_at" [absoluteOnly]="true" /></dd>
              </dl>
            </div>
          </section>
          <section class="sf-card">
            <div class="sf-card__header"><h2 class="sf-card__title">Event</h2></div>
            <div class="sf-card__body">
              <dl class="sf-dl">
                <dt>Type</dt>
                <dd>
                  <a [routerLink]="['/o', org.orgId(), 'events', d.event_id]">{{
                    d.event.event_type
                  }}</a>
                </dd>
                <dt>Status now</dt>
                <dd><sf-status [value]="d.event.status" /></dd>
                <dt>Recorded</dt>
                <dd><sf-time [value]="d.event.created_at" [absoluteOnly]="true" /></dd>
                <dt>Changed fields</dt>
                <dd>{{ d.event.changed_fields.join(', ') || '-' }}</dd>
                <dt>Event ID</dt>
                <dd><sf-id [value]="d.event_id" [short]="false" /></dd>
                <dt>Entry ID</dt>
                <dd><sf-id [value]="d.id" [short]="false" /></dd>
              </dl>
            </div>
          </section>
        </div>

        @if (otherEntries(d).length) {
          <section class="sf-card">
            <div class="sf-card__header">
              <h2 class="sf-card__title">Other dead letters for this event</h2>
            </div>
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Step</th>
                  <th scope="col">Error</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                @for (h of otherEntries(d); track h.id) {
                  <tr>
                    <td>
                      <a [routerLink]="['/o', org.orgId(), 'dead-letters', h.id]"
                        ><sf-time [value]="h.dead_lettered_at"
                      /></a>
                    </td>
                    <td>
                      <code>{{ h.operation ?? '-' }}</code>
                    </td>
                    <td>{{ humanize(h.error_category) }}</td>
                    <td><sf-status [value]="h.status" /></td>
                  </tr>
                }
              </tbody>
            </table>
          </section>
        }
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
    .inline {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
    }
    .explain {
      flex-basis: 100%;
      display: block;
      margin-top: 4px;
      color: var(--sf-text-muted);
    }
  `,
})
export class DeadLetterDetailComponent {
  readonly id = input.required<string>();

  protected readonly org = inject(OrgContextService);
  private readonly api = inject(DeadLettersApi);
  private readonly connectorsApi = inject(ConnectorsApi);
  private readonly dialogs = inject(DialogService);
  private readonly toast = inject(ToastService);
  protected readonly humanize = humanize;
  protected readonly reasons = REASONS;

  protected readonly entry = httpResource<DeadLetterDetail>(() =>
    this.api.getRequest(this.org.orgId(), this.id()),
  );
  private readonly connectors = httpResource<Page<Connector>>(() =>
    this.connectorsApi.listRequest(this.org.orgId()),
  );
  protected readonly connectorNames = computed(
    () => new Map((this.connectors.value()?.items ?? []).map((c) => [c.id, c.name])),
  );
  protected readonly busy = signal(false);
  protected readonly replayError = signal<ApiError | null>(null);

  protected readonly crumbs = computed(() => [
    { label: 'Reliability', link: ['/o', this.org.orgId(), 'reliability'] },
    { label: 'Dead-letter queue', link: ['/o', this.org.orgId(), 'dead-letters'] },
    { label: 'Entry' },
  ]);

  /** `history` lists every entry of the event, this one included. */
  protected otherEntries(d: DeadLetterDetail) {
    return d.history.filter((h) => h.id !== d.id);
  }

  protected async replay(d: DeadLetterDetail): Promise<void> {
    const ok = await this.dialogs.confirm({
      title: 'Replay this event?',
      message:
        'The failed steps run again with a fresh retry budget; steps that already succeeded are not repeated. Fix the cause first (for example the connector credentials), or the replay will fail the same way.',
      confirmLabel: 'Replay',
    });
    if (!ok) return;
    this.busy.set(true);
    this.replayError.set(null);
    this.api.replay(this.org.orgId(), d.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.entry.reload();
        this.toast.success('Replay queued; the event is being processed again');
      },
      error: (e: unknown) => {
        this.busy.set(false);
        const err = ApiError.from(e);
        this.replayError.set(err);
        if (err.code === 'already_replayed') this.entry.reload();
      },
    });
  }
}
