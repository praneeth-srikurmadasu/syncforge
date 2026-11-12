import { httpResource } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ConnectorsApi } from '../../core/api/integrations.api';
import { ConflictSeverity, Connector, Page, Policy, PolicyUpdate } from '../../core/api/models';
import { ConflictsApi } from '../../core/api/operations.api';
import { OrgContextService } from '../../core/org/org-context.service';
import { ToastService } from '../../core/toast/toast.service';
import { BadgeComponent, StatusBadgeComponent } from '../../shared/ui/badge.component';
import { IconComponent } from '../../shared/ui/icon.component';
import { PageHeaderComponent } from '../../shared/ui/page-header.component';
import { ErrorStateComponent, SkeletonComponent } from '../../shared/ui/states.component';
import { fieldLabel } from './conflict-fields';

interface Draft {
  source: string; // 'syncforge' or a connector ID
  severity: ConflictSeverity;
  resolution_mode: 'manual' | 'auto';
}

/** Which system is authoritative for each field (data_source_policies). */
@Component({
  selector: 'sf-policies',
  imports: [
    FormsModule,
    PageHeaderComponent,
    BadgeComponent,
    StatusBadgeComponent,
    IconComponent,
    ErrorStateComponent,
    SkeletonComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="sf-page">
      <sf-page-header
        title="Source-of-truth policies"
        [crumbs]="[
          { label: 'Conflicts', link: ['/o', org.orgId(), 'conflicts'] },
          { label: 'Policies' },
        ]"
        description="For each field, which system wins when SyncForge and an application disagree, how serious a difference is, and whether it is fixed automatically."
      />

      <div class="sf-alert sf-alert--info">
        <sf-icon name="info" />
        <span>
          <strong>Manual</strong>: a conflict waits for a person to decide.
          <strong>Automatic</strong>: reconciliation applies the authoritative side's value at once
          and records the decision. Fields without a saved policy use SyncForge's defaults.
        </span>
      </div>

      <div class="sf-card">
        @if (policies.error(); as err) {
          <sf-error-state [error]="err" (retry)="policies.reload()" />
        } @else if (policies.value(); as list) {
          <div class="sf-table-wrap">
            <table class="sf-table">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Authoritative system</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Resolution</th>
                  <th scope="col">Origin</th>
                  @if (canManage()) {
                    <th scope="col"><span class="sf-visually-hidden">Actions</span></th>
                  }
                </tr>
              </thead>
              <tbody>
                @for (p of list; track p.field) {
                  @if (editing() === p.field) {
                    <tr class="editing">
                      <td class="sf-cell-primary">{{ fieldLabel(p.field) }}</td>
                      <td>
                        <label class="sf-visually-hidden" [for]="'src-' + p.field"
                          >Authoritative system</label
                        >
                        <select
                          [id]="'src-' + p.field"
                          class="sf-select"
                          [(ngModel)]="draft.source"
                        >
                          <option value="syncforge">SyncForge</option>
                          @for (c of connectors.value()?.items ?? []; track c.id) {
                            <option [value]="c.id">{{ c.name }}</option>
                          }
                        </select>
                      </td>
                      <td>
                        <label class="sf-visually-hidden" [for]="'sev-' + p.field">Severity</label>
                        <select
                          [id]="'sev-' + p.field"
                          class="sf-select"
                          [(ngModel)]="draft.severity"
                        >
                          @for (s of severities; track s) {
                            <option [value]="s">{{ s }}</option>
                          }
                        </select>
                      </td>
                      <td>
                        <label class="sf-visually-hidden" [for]="'mode-' + p.field"
                          >Resolution</label
                        >
                        <select
                          [id]="'mode-' + p.field"
                          class="sf-select"
                          [(ngModel)]="draft.resolution_mode"
                        >
                          <option value="manual">Manual</option>
                          <option value="auto">Automatic</option>
                        </select>
                      </td>
                      <td></td>
                      <td class="actions">
                        <button
                          type="button"
                          class="sf-btn sf-btn--sm sf-btn--primary"
                          [disabled]="busy()"
                          (click)="save(p)"
                        >
                          Save
                        </button>
                        <button type="button" class="sf-btn sf-btn--sm" (click)="editing.set(null)">
                          Cancel
                        </button>
                      </td>
                    </tr>
                  } @else {
                    <tr>
                      <td class="sf-cell-primary">{{ fieldLabel(p.field) }}</td>
                      <td>
                        @if (p.source === 'syncforge') {
                          SyncForge
                        } @else {
                          {{ connectorNames().get(p.connector_id ?? '') ?? 'Connector' }}
                        }
                      </td>
                      <td><sf-status [value]="p.severity" /></td>
                      <td>{{ p.resolution_mode === 'auto' ? 'Automatic' : 'Manual' }}</td>
                      <td>
                        <sf-badge [tone]="p.configured ? 'accent' : 'neutral'">{{
                          p.configured ? 'Saved policy' : 'Default'
                        }}</sf-badge>
                      </td>
                      @if (canManage()) {
                        <td class="actions">
                          <button
                            type="button"
                            class="sf-btn sf-btn--ghost sf-btn--sm"
                            (click)="edit(p)"
                            [attr.aria-label]="'Edit policy for ' + fieldLabel(p.field)"
                          >
                            <sf-icon name="pencil" [size]="13" /> Edit
                          </button>
                        </td>
                      }
                    </tr>
                  }
                }
              </tbody>
            </table>
          </div>
        } @else {
          <sf-skeleton [rows]="7" />
        }
      </div>
      @if (!canManage()) {
        <p class="sf-faint small">Only organization administrators can change policies.</p>
      }
    </div>
  `,
  styles: `
    .actions {
      text-align: right;
      white-space: nowrap;
    }
    .editing .sf-select {
      height: 30px;
      min-width: 140px;
    }
    .small {
      font-size: var(--sf-text-xs);
    }
  `,
})
export class PoliciesComponent {
  protected readonly org = inject(OrgContextService);
  private readonly api = inject(ConflictsApi);
  private readonly connectorsApi = inject(ConnectorsApi);
  private readonly toast = inject(ToastService);
  protected readonly fieldLabel = fieldLabel;
  protected readonly severities: ConflictSeverity[] = ['low', 'medium', 'high', 'critical'];

  protected readonly policies = httpResource<Policy[]>(() =>
    this.api.policiesRequest(this.org.orgId()),
  );
  protected readonly connectors = httpResource<Page<Connector>>(() =>
    this.connectorsApi.listRequest(this.org.orgId()),
  );
  protected readonly connectorNames = computed(
    () => new Map((this.connectors.value()?.items ?? []).map((c) => [c.id, c.name])),
  );
  protected readonly canManage = computed(() => {
    this.org.organization();
    return this.org.can('policies:manage');
  });

  protected readonly editing = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected draft: Draft = { source: 'syncforge', severity: 'medium', resolution_mode: 'manual' };

  protected edit(p: Policy): void {
    this.draft = {
      source: p.source === 'connector' && p.connector_id ? p.connector_id : 'syncforge',
      severity: p.severity,
      resolution_mode: p.resolution_mode,
    };
    this.editing.set(p.field);
  }

  protected save(p: Policy): void {
    const body: PolicyUpdate =
      this.draft.source === 'syncforge'
        ? {
            source: 'syncforge',
            connector_id: null,
            severity: this.draft.severity,
            resolution_mode: this.draft.resolution_mode,
          }
        : {
            source: 'connector',
            connector_id: this.draft.source,
            severity: this.draft.severity,
            resolution_mode: this.draft.resolution_mode,
          };
    this.busy.set(true);
    this.api.updatePolicy(this.org.orgId(), p.field, body).subscribe({
      next: () => {
        this.busy.set(false);
        this.editing.set(null);
        this.policies.reload();
        this.toast.success(`Policy for ${fieldLabel(p.field)} saved`);
      },
      error: (e: unknown) => {
        this.busy.set(false);
        this.toast.error(e, 'Policy not saved');
      },
    });
  }
}
